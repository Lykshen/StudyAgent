"""业务规则测试：用户隔离、提交幂等、错题间隔、代码超时、计划、组卷、试卷快照、交卷、复核、导出。
不需要模型。运行：python tests/test_rules.py"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
DATA = os.path.join(tempfile.gettempdir(), "sa_rules")
os.environ["STUDYAGENT_DATA"] = DATA
shutil.rmtree(DATA, ignore_errors=True)

from studyagent import create_app, db, grading  # noqa: E402
from studyagent import learning as L  # noqa: E402

app = create_app()
c = app.test_client()
LOCAL = {"REMOTE_ADDR": "127.0.0.1"}
A = {"Authorization": "Bearer " + c.get("/api/session/local", environ_base=LOCAL).json["token"]}
ok = fail = 0


def check(cond, label):
    global ok, fail
    print(("PASS " if cond else "FAIL ") + label)
    if cond:
        ok += 1
    else:
        fail += 1


def uid_of(h):
    return db.q1("SELECT id FROM users WHERE token=?", (h["Authorization"][7:],))["id"]


# ---------- 用户隔离 ----------
bcode = c.post("/api/users", json={"name": "B"}, headers=A).json["code"]
B = {"Authorization": "Bearer " + bcode}
qa = c.post("/api/questions", json={"type": "single", "title": "A 的私有题", "stem": "1+1=?", "options": ["1", "2"], "answer": 1}, headers=A).json["id"]
check(c.get("/api/questions/" + qa, headers=B).status_code == 404, "B 不能读取 A 的私有题")
check(all(q["id"] != qa for q in c.get("/api/questions", headers=B).json), "A 的私有题不出现在 B 的题库")
conv = c.post("/api/conversations", json={"agent": "tutor"}, headers=A).json["id"]
check(c.get("/api/conversations/%d" % conv, headers=B).status_code == 404, "B 不能读取 A 的对话")
c.post("/api/models", json={"preset": "deepseek", "name": "A 的模型", "api_key": "sk-secret-abcdef123456"}, headers=A)
check(all(m["name"] != "A 的模型" for m in c.get("/api/models", headers=B).json["models"]), "B 看不到 A 的模型配置")
check(c.post("/api/users", json={"name": "C"}, headers=B).status_code == 403, "普通用户不能创建用户")

# ---------- 提交幂等 ----------
r1 = c.post("/api/questions/%s/submit" % qa, json={"answer": 0, "idem": "same-1"}, headers=A).json
r2 = c.post("/api/questions/%s/submit" % qa, json={"answer": 0, "idem": "same-1"}, headers=A).json
n = db.q1("SELECT COUNT(*) n FROM attempts WHERE idem='same-1'")["n"]
check(r2.get("duplicate") and r2["attempt_id"] == r1["attempt_id"] and n == 1, "重复提交只生成一次结果")

# ---------- 错题间隔 1/3/7/14 ----------
ua = uid_of(A)
rv = db.q1("SELECT * FROM reviews WHERE user_id=? AND question_id=?", (ua, qa))
check(rv and rv["stage"] == 0 and rv["due"] == L.add_days(L.today(), 1), "答错进入错题本，1 天后复习")
c.post("/api/questions/%s/submit" % qa, json={"answer": 1, "idem": "early"}, headers=A)
rv = db.q1("SELECT * FROM reviews WHERE user_id=? AND question_id=?", (ua, qa))
check(rv["stage"] == 0, "未到期重做不算复习")
db.run("UPDATE reviews SET due=? WHERE user_id=? AND question_id=?", (L.today(), ua, qa))
c.post("/api/questions/%s/submit" % qa, json={"answer": 1, "idem": "due-ok"}, headers=A)
rv = db.q1("SELECT * FROM reviews WHERE user_id=? AND question_id=?", (ua, qa))
check(rv["stage"] == 1 and rv["due"] == L.add_days(L.today(), 3), "到期答对进入下一轮（3 天后）")
db.run("UPDATE reviews SET due=? WHERE user_id=? AND question_id=?", (L.today(), ua, qa))
c.post("/api/questions/%s/submit" % qa, json={"answer": 0, "idem": "due-bad"}, headers=A)
rv = db.q1("SELECT * FROM reviews WHERE user_id=? AND question_id=?", (ua, qa))
check(rv["stage"] == 0 and len(json.loads(rv["history"])) == 2, "到期答错回到第一轮，历史保留")

# ---------- 多选与填空规则 ----------
qm = c.post("/api/questions", json={"type": "multi", "title": "多选", "stem": "选偶数", "options": ["1", "2", "3", "4"], "answer": [1, 3]}, headers=A).json["id"]
check(c.post("/api/questions/%s/submit" % qm, json={"answer": [1]}, headers=A).json["ratio"] == 0, "多选漏选不得分")
check(c.post("/api/questions/%s/submit" % qm, json={"answer": [3, 1]}, headers=A).json["ratio"] == 1, "多选全对得分（顺序无关）")
qf = c.post("/api/questions", json={"type": "fill", "title": "填空", "stem": "首都__，年份__", "answer": [["北京", "Beijing"], ["1949"]]}, headers=A).json["id"]
check(c.post("/api/questions/%s/submit" % qf, json={"answer": ["beijing", "1949"]}, headers=A).json["ratio"] == 1, "填空多个可接受答案、不区分大小写")
check(c.post("/api/questions/%s/submit" % qf, json={"answer": ["北京", "1950"]}, headers=A).json["ratio"] == 0.5, "填空按空计分")

# ---------- 代码运行 ----------
r = grading.run_code("python", "def solve(x):\n    while True:\n        pass\n", [{"args": [1], "expect": 1}, {"args": [2], "expect": 2}], per_case=1.0)
check([x["kind"] for x in r["results"]] == ["TLE", "SKIP"], "超时记为 TLE，之后的用例记为 SKIP")
r = grading.run_code("python", "def solve(a):\n    return sorted(Counter(a).items())\n", [{"args": [[1, 1, 2]], "expect": [[1, 2], [2, 1]]}])
check(r["results"][0]["pass"], "预置力扣常用导入（Counter 等）")
r = grading.run_code("python", "def solve(a):\n    return 1/0\n", [{"args": [1], "expect": 1}])
check(r["results"][0]["kind"] == "RE", "异常记为 RE")

# ---------- 计划：月末规则与容量 ----------
check(c.put("/api/goal", json={"start_date": "2027-03-01", "exam_date": "2027-02-01"}, headers=A).status_code == 400, "考试日期必须晚于开始日期")
c.put("/api/goal", json={"start_date": "2027-01-25", "exam_date": "2027-03-20", "monthly_day": 31, "weekly_day": 0, "hours": 0.5, "overflow": "trim"}, headers=A)
p = c.get("/api/plan", headers=A).json
pl = p.get("plan", p)
mon = [d["date"] for d in pl["days"] if d["ev"] == "monthly"]
check("2027-01-31" in mon and "2027-02-28" in mon, "月测选 31 号，2 月落在月末")
check(pl["days"][-1]["ev"] == "monthly", "考试前一天固定安排月测")
check(all(d["ev"] == "weekly" for d in pl["days"] if L.dt.date.fromisoformat(d["date"]).isoweekday() == 7 and d["ev"] != "monthly"), "周测落在指定星期")
check(pl["over"] > 0 and pl["mode"] == "trim" and pl["trimmed"], "时间不够时显示缺口并按选择缩小范围")
check(any(d["sprint"] for d in pl["days"]) and not any(t["type"] == "q" and d["sprint"] for d in pl["days"][:-pl["sprint"]] for t in d["tasks"]), "末尾留出冲刺期")

# ---------- 组卷缺口 ----------
r = c.post("/api/exams", json={"type": "custom", "scope": "weak"}, headers=B).json
check(bool(r.get("gaps")) and "id" not in r, "题量不足时报告缺口，不生成试卷")

# ---------- 试卷快照、交卷、复核 ----------
eid = c.post("/api/exams", json={"type": "custom", "scope": "all", "allow_recent": True}, headers=A).json["id"]
e = c.post("/api/exams/%d/start" % eid, headers=A).json
it = e["paper"]["items"][0]
check("answer" not in it and "hidden" not in json.dumps(it.get("extra", {})), "考试中不下发答案和隐藏用例")
old_title = it["title"]
check(c.put("/api/questions/" + it["qid"], json={"title": "改过的题名"}, headers=A).status_code == 200, "考试中管理员修改源题")
check(c.get("/api/exams/%d" % eid, headers=A).json["paper"]["items"][0]["title"] == old_title, "试卷快照不受改题影响")
check(c.get("/api/exams/%d" % eid, headers=B).status_code == 404, "B 不能读取 A 的试卷")
c.put("/api/questions/" + it["qid"], json={"title": old_title}, headers=A)
s1 = c.post("/api/exams/%d/submit" % eid, json={}, headers=A).json
s2 = c.post("/api/exams/%d/submit" % eid, json={}, headers=A).json
n = db.q1("SELECT COUNT(*) n FROM attempts WHERE mode='exam' AND user_id=?", (ua,))["n"]
check(s1["status"] == "done" and s1["result"] == s2["result"] and n == len(e["paper"]["items"]), "重复交卷只有一份成绩")
check(c.put("/api/exams/%d/answers" % eid, json={"answers": {}}, headers=A).status_code == 409, "交卷后不能再保存答案")
check(c.post("/api/exams/%d/adjust" % eid, json={"qid": it["qid"], "score": 50}, headers=A).status_code == 400, "复核必须写理由")
c.post("/api/exams/%d/adjust" % eid, json={"qid": it["qid"], "score": 50, "reason": "人工复核"}, headers=A)
ex = c.get("/api/exams/%d" % eid, headers=A).json
adj = ex["adjustments"]
check(len(adj) == 1 and adj[0]["old"] == s1["result"]["items"][0]["score"] and adj[0]["new"] == 50 and adj[0]["reason"] == "人工复核",
      "复核保留原分、新分、理由")
check(db.q1("SELECT 1 FROM audit WHERE action='exam.adjust' AND target=?", (str(eid),)) is not None, "复核写入审计日志")

eid2 = c.post("/api/exams", json={"type": "custom", "scope": "all", "allow_recent": True}, headers=A).json["id"]
c.post("/api/exams/%d/start" % eid2, headers=A)
db.run("UPDATE exams SET deadline_at=? WHERE id=?", (time.time() - 1, eid2))
e2 = c.get("/api/exams/%d" % eid2, headers=A).json
check(e2["status"] == "done" and e2["result"]["auto"], "到时自动交卷")

d1 = c.post("/api/exams", json={"type": "weekly", "scope": "all", "allow_recent": True, "sched_date": "2027-02-07"}, headers=A).json["id"]
d2 = c.post("/api/exams", json={"type": "weekly", "scope": "all", "allow_recent": True, "sched_date": "2027-02-07"}, headers=A).json["id"]
check(d1 == d2, "同一日期的定期测试不重复生成")

# ---------- 局域网开关 ----------
from studyagent import config  # noqa: E402
PHONE = {"REMOTE_ADDR": "192.168.1.50"}
config.save(lan=False)
r = c.get("/api/ping", environ_base=PHONE)
check(r.status_code == 403 and r.json.get("lan_off") and r.headers.get("Access-Control-Allow-Origin") == "*", "未开启时拒绝其它设备，并说明原因（App 可读）")
check(c.get("/api/ping", environ_base=LOCAL).status_code == 200, "本机始终可用")
os.environ["SA_BIND_ALL"] = "1"
c.put("/api/settings/lan", json={"lan": True}, headers=A)
r = c.get("/api/ping", environ_base=PHONE)
check(r.status_code == 200 and r.json["app"] == "StudyAgent" and r.headers.get("Access-Control-Allow-Origin") == "*", "开启后立即生效，App 能跨域检测")
check(c.post("/api/session/login", json={"code": bcode}, environ_base=PHONE).status_code == 200, "开启后手机能用访问码登录")
check(c.get("/api/session/local", environ_base=PHONE).status_code == 403, "其它设备不能免登录")
check(c.post("/api/settings/firewall", json={}, headers=A, environ_base=PHONE).status_code == 403, "防火墙设置只能在本机操作")
sy = c.get("/api/system", headers=A).json
check(sy["lan_running"] and not sy["lan_restart"], "系统状态显示正在接受连接")
os.environ["SA_BIND_ALL"] = "0"
check(c.get("/api/system", headers=A).json["lan_restart"], "只监听本机时提示需要重新打开")
c.put("/api/settings/lan", json={"lan": False}, headers=A)

# ---------- 导出 ----------
raw = c.get("/api/export", headers=A).get_data(as_text=True)
check("sk-secret-abcdef123456" not in raw and json.loads(raw)["tables"]["attempts"], "导出含作答记录，不含 API Key")
check("sk-secret-abcdef123456" not in json.dumps(c.get("/api/models", headers=A).json), "接口不返回完整 API Key")

print()
print("ALL %d CHECKS PASSED" % ok if not fail else "%d FAILED, %d passed" % (fail, ok))
sys.exit(1 if fail else 0)
