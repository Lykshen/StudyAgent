"""End-to-end API test with mock model servers. Run: python tests/test_api.py"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
DATA = os.path.join(tempfile.gettempdir(), "sa_e2e")
os.environ["STUDYAGENT_DATA"] = DATA
shutil.rmtree(DATA, ignore_errors=True)

import mock_llm  # noqa
from studyagent import create_app  # noqa

mock_llm.serve(9911)
app = create_app()
c = app.test_client()
tok = c.get("/api/session/local", environ_base={"REMOTE_ADDR": "127.0.0.1"}).json["token"]
H = {"Authorization": "Bearer " + tok}
ok = 0


def check(cond, label):
    global ok
    print(("PASS " if cond else "FAIL ") + label)
    if cond:
        ok += 1
    else:
        raise SystemExit(1)


def sse(resp):
    evs = []
    for line in resp.get_data(as_text=True).splitlines():
        if line.startswith("data: "):
            ev = json.loads(line[6:])
            if ev.get("type"):
                evs.append(ev)
    return evs


# remote device without code is refused
check(c.get("/api/session/local", environ_base={"REMOTE_ADDR": "192.168.1.9"}).status_code == 403, "LAN device cannot auto-login")
check(c.post("/api/session/login", json={"code": tok}).status_code == 200, "login with access code")

# models: bad key, good key, anthropic
m_bad = c.post("/api/models", headers=H, json={"preset": "deepseek", "base_url": "http://127.0.0.1:9911/v1", "api_key": "wrong"}).json["id"]
t = c.post("/api/models/%d/test" % m_bad, headers=H).json
check(not t["ok"] and "认证失败" in t["error"] and "wrong" not in json.dumps(t), "auth failure is reported without leaking key")
m_oa = c.post("/api/models", headers=H, json={"preset": "deepseek", "name": "模拟 OpenAI 兼容", "base_url": "http://127.0.0.1:9911/v1", "api_key": "good-key"}).json["id"]
t = c.post("/api/models/%d/test" % m_oa, headers=H).json
check(t["ok"] and t["reply"] == "连接正常" and t["tools"], "OpenAI-compatible test + tool calling")
m_an = c.post("/api/models", headers=H, json={"preset": "claude", "name": "模拟 Claude", "base_url": "http://127.0.0.1:9911", "api_key": "good-key"}).json["id"]
t = c.post("/api/models/%d/test" % m_an, headers=H).json
check(t["ok"] and t["tools"], "Anthropic test + tool calling")
ms = c.get("/api/models", headers=H).json["models"]
check(all("api_key" not in m for m in ms) and any(m["key_hint"].startswith("…") for m in ms), "API keys never returned")
c.delete("/api/models/%d" % m_bad, headers=H)
c.put("/api/routes", headers=H, json={"chat": m_oa, "plan": m_an, "classify": m_oa, "import": m_an, "grade": m_oa, "lesson": m_an})

# agent: tool call + streaming + proposal confirmation (OpenAI-compatible)
conv = c.post("/api/conversations", headers=H, json={"agent": "tutor"}).json["id"]
evs = sse(c.post("/api/conversations/%d/send" % conv, headers=H, json={"text": "今天做什么？"}))
types = [e["type"] for e in evs]
check("tool" in types and "tool_result" in types and types[-1] == "done", "tutor agent calls get_today_plan and finishes")
check(sum(1 for e in evs if e["type"] == "delta") > 1, "final answer streamed in chunks")
evs = sse(c.post("/api/conversations/%d/send" % conv, headers=H, json={"text": "帮我调整我的计划"}))
props = [e["proposal"] for e in evs if e["type"] == "proposal"]
check(len(props) == 1 and props[0]["kind"] == "plan", "plan change becomes a proposal")
g_before = c.get("/api/plan", headers=H).json["goal"]["hours"]
check(g_before == 1.5, "plan unchanged before confirmation")
c.post("/api/proposals/%d" % props[0]["id"], headers=H, json={"accept": True})
check(c.get("/api/plan", headers=H).json["goal"]["hours"] == 2.5, "plan changed after confirmation")
check(c.post("/api/proposals/%d" % props[0]["id"], headers=H, json={"accept": True}).status_code == 400, "proposal cannot be applied twice")
msgs = c.get("/api/conversations/%d" % conv, headers=H).json["messages"]
check(len(msgs) == 4 and "模拟 OpenAI" in (msgs[-1]["model"] or ""), "conversation stored with model label")

# planner agent on Anthropic adapter
conv2 = c.post("/api/conversations", headers=H, json={"agent": "planner"}).json["id"]
evs = sse(c.post("/api/conversations/%d/send" % conv2, headers=H, json={"text": "请调整我的计划"}))
check(any(e["type"] == "proposal" for e in evs) and evs[-1]["type"] == "done", "planner agent via Anthropic adapter proposes change")

# import job (mixed types) -> review -> save
j = c.post("/api/jobs/import", headers=H, json={"text": "一些题目文字……"}).json
for _ in range(50):
    j = c.get("/api/jobs/" + j["id"], headers=H).json
    if j["status"] != "running":
        break
    time.sleep(0.1)
items = j["result"]
check(j["status"] == "done" and {i["type"] for i in items} == {"single", "multi", "judge", "fill", "short", "code"}, "import parses 6 question types")
single = next(i for i in items if i["type"] == "single")
check(single["answer"] == 0 and next(i for i in items if i["type"] == "multi")["answer"] == [0, 2], "letter answers mapped to option indexes")
check(single["cls"]["category_name"] == "几何", "unknown category suggested as new")
saved = c.post("/api/import/save", headers=H, json={"items": items, "source": "测试"}).json["ids"]
check(len(saved) == 6, "imported questions saved")
cats = c.get("/api/categories", headers=H).json
check(any(x["name"] == "几何" for x in cats), "new category created on import")

# practice on imported objective questions
qid = {c.get("/api/questions/" + i, headers=H).json["question"]["type"]: i for i in saved}
r = c.post("/api/questions/%s/submit" % qid["single"], headers=H, json={"answer": 0}).json
check(r["full"] and r["answer"] == 0, "single choice graded")
r = c.post("/api/questions/%s/submit" % qid["multi"], headers=H, json={"answer": [0]}).json
check(not r["full"] and r["review"]["due"], "multi choice all-or-nothing + added to review")
r = c.post("/api/questions/%s/submit" % qid["fill"], headers=H, json={"answer": [" 3.14 "]}).json
check(r["full"], "fill blank ignores spaces")
r = c.post("/api/questions/%s/submit" % qid["judge"], headers=H, json={"answer": True}).json
check(r["full"], "judge graded")
r = c.post("/api/questions/%s/submit" % qid["short"], headers=H, json={"answer": "要求数组有序，复杂度对数"}).json
check(r["full"] and r["detail"]["ai"], "short answer AI-graded and marked")
r = c.post("/api/questions/%s/submit" % qid["code"], headers=H, json={"lang": "python", "code": "def solve(a,b):\n    return a+b"}).json
check(r["full"], "imported code question runs")

# AI classify job -> apply
j = c.post("/api/jobs/classify", headers=H, json={"scope": "default"}).json
for _ in range(100):
    j = c.get("/api/jobs/" + j["id"], headers=H).json
    if j["status"] != "running":
        break
    time.sleep(0.1)
check(j["status"] == "done" and len(j["result"]) >= 140, "classify job over the bank")
before = c.get("/api/questions/p1", headers=H).json["question"]
ap = c.post("/api/classify/apply", headers=H, json={"results": {"p1": j["result"]["p1"]}}).json
after = c.get("/api/questions/p1", headers=H).json["question"]
check(ap["applied"] == 1 and after["cls_by"] == "ai" and after["tier"] == j["result"]["p1"]["tier"], "classification applied only after confirmation")

# lesson generation draft -> save
cat = next(x for x in cats if x["name"] == "几何")
d = c.post("/api/lessons/%d/generate" % cat["id"], headers=H).json["draft"]
check(d["name"] == "几何" and len(d["quiz"]) == 1, "lesson draft generated, invalid quiz items dropped")
c.put("/api/lessons/%d" % cat["id"], headers=H, json={"content": d})
check(c.get("/api/lessons/%d" % cat["id"], headers=H).json["lesson"]["intro"] == "模拟课程", "lesson saved")

# question AI helper stream + assist recorded
evs = sse(c.post("/api/questions/p5/ai", headers=H, json={"kind": "hint"}))
check(evs[-1]["type"] == "done", "question AI helper streams")
check(c.get("/api/questions/p5", headers=H).json["progress"]["assist"].get("hint") == 1, "hint usage recorded")

# background runs: leaving the page does not end the reply
conv3 = c.post("/api/conversations", headers=H, json={"agent": "tutor"}).json["id"]
resp = c.post("/api/conversations/%d/send" % conv3, headers=H, json={"text": "请慢一点讲"}, buffered=False)
first = next(resp.response)            # read only the opening chunk, then "leave the page"
resp.close()
time.sleep(0.6)
g = c.get("/api/conversations/%d" % conv3, headers=H).json
check(g["running"] is True, "reply keeps generating after the client disconnects")
check(c.post("/api/conversations/%d/send" % conv3, headers=H, json={"text": "再问一句"}).status_code == 409, "second message refused while a reply is generating")
evs = sse(c.get("/api/conversations/%d/attach?from=0" % conv3, headers=H))
check(evs[-1]["type"] == "done" and sum(1 for e in evs if e["type"] == "delta") > 5, "re-attaching replays the whole reply to the end")
g = c.get("/api/conversations/%d" % conv3, headers=H).json
check(not g["running"] and g["messages"][-1]["status"] == "done" and g["messages"][-1]["content"].count("分步回答") == 12, "full reply saved")
# stop
resp = c.post("/api/conversations/%d/send" % conv3, headers=H, json={"text": "请慢一点再讲一遍"}, buffered=False)
next(resp.response); resp.close(); time.sleep(0.6)
c.post("/api/conversations/%d/stop" % conv3, headers=H)
evs = sse(c.get("/api/conversations/%d/attach?from=0" % conv3, headers=H))
g = c.get("/api/conversations/%d" % conv3, headers=H).json
check(evs[-1]["type"] == "stopped" and "已停止生成" in g["messages"][-1]["content"], "stop button stops the reply and keeps what was written")
# empty answer after tool calls is recovered
evs = sse(c.post("/api/conversations/%d/send" % conv3, headers=H, json={"text": "空回复测试"}))
g = c.get("/api/conversations/%d" % conv3, headers=H).json
check(evs[-1]["type"] == "done" and g["messages"][-1]["content"].startswith("补充回答"), "empty final answer recovered with a follow-up call")

# usage
u = c.get("/api/usage", headers=H).json
check(sum(r["n"] for r in u) > 5 and any(r["status"] == "auth" for r in u), "usage recorded incl. failures")

# exam during running blocks chat
e = c.post("/api/exams", headers=H, json={"type": "weekly", "scope": "all"}).json
c.post("/api/exams/%d/start" % e["id"], headers=H)
check(c.post("/api/conversations/%d/send" % conv, headers=H, json={"text": "hi"}).status_code == 409, "AI disabled during a running test")
c.delete("/api/exams/%d" % e["id"], headers=H)

# export / import roundtrip
data = c.get("/api/export", headers=H).get_data(as_text=True)
check(len(json.loads(data)["tables"]["attempts"]) >= 6, "export contains attempts")
print("\nALL %d CHECKS PASSED" % ok)
