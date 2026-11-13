"""HTTP API (Flask). Every route is a plain JSON endpoint so other clients (mobile, desktop, scripts) can use the same platform."""
import json
import os
import queue
import secrets
import socket
import sys
import threading
import time
import uuid
from functools import wraps

from flask import Blueprint, Response, jsonify, request, send_from_directory

from . import agents, db, exams, grading, importer, learning as L, llm

bp = Blueprint("api", __name__)
WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
VERSION = "1.0.0"


# ---------------- helpers ----------------
def err(msg, code=400, **extra):
    return jsonify({"error": msg, **extra}), code


def current_user():
    tok = request.headers.get("Authorization", "").replace("Bearer ", "").strip() or request.cookies.get("sa_token") or request.args.get("token")
    return db.q1("SELECT * FROM users WHERE token=?", (tok,)) if tok else None


def auth(admin=False):
    def deco(f):
        @wraps(f)
        def w(*a, **k):
            u = current_user()
            if not u:
                return err("请先登录（输入访问码）", 401)
            if admin and u["role"] != "admin":
                return err("需要管理员权限", 403)
            request.user = u
            return f(*a, **k)
        return w
    return deco


def uid():
    return request.user["id"]


def body():
    return request.get_json(silent=True) or {}


def lan_addresses(port):
    """LAN URLs of this computer. The first one is the address of the default route (usually Wi-Fi /
    Ethernet); the rest may be virtual adapters (VPN, Hyper-V, WSL, VMware)."""
    primary, others = None, set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        primary = s.getsockname()[0]
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            others.add(info[4][0])
    except Exception:
        pass
    ips = ([primary] if primary and not primary.startswith(("127.", "169.254.")) else []) + \
        sorted(ip for ip in others if ip != primary and not ip.startswith(("127.", "169.254.")))
    return ["http://%s:%s" % (ip, port) for ip in ips]


LOOPBACK = ("127.0.0.1", "::1")


def bound_to_network():
    """True when the server listens on all interfaces (desktop program always does)."""
    return os.environ.get("SA_BIND_ALL") == "1"


def lan_running():
    from . import config
    return bound_to_network() and bool(config.load()["lan"])


def lan_restart_needed():
    from . import config
    return bool(config.load()["lan"]) and not bound_to_network()


@bp.before_app_request
def lan_gate():
    """Other devices may connect only while 「允许手机连接」 is on (takes effect immediately)."""
    if request.remote_addr in LOOPBACK or request.remote_addr is None:
        return None
    from . import config
    if config.load()["lan"]:
        return None
    r = jsonify({"error": "这台电脑上的 StudyAgent 没有开启「允许手机连接」。请在电脑上打开：设置 → 设备与互通 → 允许手机连接。", "lan_off": True})
    r.status_code = 403
    r.headers["Access-Control-Allow-Origin"] = "*"
    return r


def sse(gen_fn):
    """Run gen_fn(emit) in a thread; stream its events. Client disconnect sets cancel flag."""
    qu = queue.Queue()
    cancel = threading.Event()

    Cancelled = llm.Cancelled

    def emit(ev):
        if cancel.is_set():
            raise Cancelled()
        qu.put(ev)

    user = request.user

    def worker():
        request_user = user  # noqa
        try:
            res = gen_fn(emit)
            qu.put({"type": "done", **(res or {})})
        except Cancelled:
            qu.put({"type": "stopped"})
        except llm.LLMError as e:
            qu.put({"type": "error", "message": str(e), "code": e.code, "retryable": e.retryable})
        except Exception as e:
            qu.put({"type": "error", "message": "出错了：%s" % e})
        qu.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        try:
            yield "event: open\ndata: {}\n\n"
            while True:
                try:
                    ev = qu.get(timeout=15)
                except queue.Empty:
                    yield ": ping\n\n"
                    continue
                if ev is None:
                    break
                yield "data: %s\n\n" % json.dumps(ev, ensure_ascii=False)
        except GeneratorExit:
            cancel.set()
            raise
    return Response(stream(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------- background jobs (import / classify) ----------------
JOBS = {}


def start_job(user_id, kind, fn):
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "user_id": user_id, "kind": kind, "status": "running", "done": 0, "total": 0, "result": None, "error": None, "cancel": False, "started": time.time()}
    JOBS[jid] = job

    def progress(d, t, partial):
        job["done"], job["total"], job["result"] = d, t, partial

    def run():
        try:
            job["result"] = fn(progress, lambda: job["cancel"])
            job["status"] = "cancelled" if job["cancel"] else "done"
        except Exception as e:
            job["status"], job["error"] = "error", str(e)
    threading.Thread(target=run, daemon=True).start()
    return job


def job_view(j):
    return {k: j[k] for k in ("id", "kind", "status", "done", "total", "result", "error")}


# ---------------- session ----------------
@bp.get("/api/session/local")
def local_session():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return err("只能在运行平台的这台电脑上自动登录；其它设备请输入访问码", 403)
    u = db.local_user()
    return jsonify({"token": u["token"], "user": {"id": u["id"], "name": u["name"], "role": u["role"]}})


@bp.post("/api/session/login")
def login():
    code = (body().get("code") or "").strip()
    u = db.q1("SELECT * FROM users WHERE token=?", (code,)) if code else None
    if not u:
        return err("访问码不对", 401)
    return jsonify({"token": u["token"], "user": {"id": u["id"], "name": u["name"], "role": u["role"]}})


@bp.get("/api/bootstrap")
@auth()
def bootstrap():
    u = request.user
    g = L.ensure_goal(uid())
    port = request.host.split(":")[-1] if ":" in request.host else "80"
    return jsonify({
        "version": VERSION, "user": {"id": u["id"], "name": u["name"], "role": u["role"]}, "goal": g,
        "subjects": db.q("SELECT id, name, description, exam_profile FROM subjects WHERE owner_id IS NULL OR owner_id=? ORDER BY id", (uid(),)),
        "tiers": {k: {"name": L.TIER_NAMES[k], "desc": L.TIER_DESC[k]} for k in L.TIER_NAMES}, "types": L.TYPE_NAMES,
        "languages": grading.languages(), "agents": agents.agent_list(), "tasks": llm.TASKS,
        "models": [llm.public_model(m) for m in db.q("SELECT * FROM model_configs WHERE owner_id IS NULL OR owner_id=? ORDER BY id", (uid(),))],
        "lan": lan_addresses(port), "lan_enabled": lan_running(),
        "pending_proposals": db.q1("SELECT COUNT(*) n FROM proposals WHERE user_id=? AND status='pending'", (uid(),))["n"],
    })


@bp.get("/api/users")
@auth(admin=True)
def users_list():
    return jsonify([{"id": u["id"], "name": u["name"], "role": u["role"], "code": u["token"]} for u in db.q("SELECT * FROM users ORDER BY id")])


@bp.post("/api/users")
@auth(admin=True)
def users_create():
    name = (body().get("name") or "").strip() or "新用户"
    tok = secrets.token_urlsafe(24)
    i = db.run("INSERT INTO users(name, token, role, created_at) VALUES (?,?,?,?)", (name, tok, "user", time.time()))
    db.audit(uid(), "user.create", str(i), {"name": name})
    return jsonify({"id": i, "name": name, "code": tok})


@bp.post("/api/users/<int:i>/reset")
@auth(admin=True)
def users_reset(i):
    tok = secrets.token_urlsafe(24)
    db.run("UPDATE users SET token=? WHERE id=?", (tok, i))
    db.audit(uid(), "user.reset_code", str(i))
    return jsonify({"id": i, "code": tok})


@bp.put("/api/me")
@auth()
def me_update():
    b = body()
    if b.get("name"):
        db.run("UPDATE users SET name=? WHERE id=?", (b["name"][:30], uid()))
    return jsonify({"ok": True})


# ---------------- subjects & categories ----------------
@bp.post("/api/subjects")
@auth()
def subject_create():
    b = body()
    if not (b.get("name") or "").strip():
        return err("学科名称不能为空")
    sid = db.run("INSERT INTO subjects(owner_id, name, description, exam_profile, created_at) VALUES (?,?,?,?,?)",
                 (uid() if request.user["role"] != "admin" else None, b["name"].strip()[:40], b.get("description", ""), db.dumps(b.get("exam_profile") or {}), time.time()))
    for i, c in enumerate(b.get("categories") or []):
        db.run("INSERT INTO categories(subject_id, name, sort) VALUES (?,?,?)", (sid, str(c)[:40], i + 1))
    return jsonify({"id": sid})


@bp.put("/api/subjects/<int:sid>")
@auth()
def subject_update(sid):
    b = body()
    s = db.q1("SELECT * FROM subjects WHERE id=?", (sid,))
    if not s or (s["owner_id"] and s["owner_id"] != uid() and request.user["role"] != "admin"):
        return err("没有权限", 403)
    for k in ("name", "description"):
        if k in b:
            db.run("UPDATE subjects SET %s=? WHERE id=?" % k, (b[k], sid))
    if "exam_profile" in b:
        db.run("UPDATE subjects SET exam_profile=? WHERE id=?", (db.dumps(b["exam_profile"]), sid))
    return jsonify({"ok": True})


@bp.get("/api/categories")
@auth()
def categories():
    sid = request.args.get("subject") or L.ensure_goal(uid())["subject_id"]
    cats = db.q("SELECT * FROM categories WHERE subject_id=? ORDER BY sort, id", (sid,))
    lessons = {r["category_id"]: r for r in db.q("SELECT category_id, status, generated_by, content FROM lessons")}
    for c in cats:
        les = lessons.get(c["id"])
        c["lesson"] = {"status": les["status"], "by": les["generated_by"], "minutes": db.J(les["content"], {}).get("minutes", 30)} if les else None
        c["lesson_done"] = L.lesson_done(uid(), c["id"])
    return jsonify(cats)


@bp.post("/api/categories")
@auth()
def category_create():
    b = body()
    sid = b.get("subject_id") or L.ensure_goal(uid())["subject_id"]
    mx = (db.q1("SELECT MAX(sort) m FROM categories WHERE subject_id=?", (sid,)) or {}).get("m") or 0
    cid = db.run("INSERT INTO categories(subject_id, name, sort, description) VALUES (?,?,?,?)", (sid, (b.get("name") or "新分类")[:40], mx + 1, b.get("description", "")))
    return jsonify({"id": cid})


@bp.put("/api/categories/<int:cid>")
@auth()
def category_update(cid):
    b = body()
    for k in ("name", "description", "sort", "enabled"):
        if k in b:
            db.run("UPDATE categories SET %s=? WHERE id=?" % k, (b[k], cid))
    return jsonify({"ok": True})


# ---------------- questions ----------------
@bp.get("/api/questions")
@auth()
def questions_list():
    a = request.args
    sid = a.get("subject") or L.ensure_goal(uid())["subject_id"]
    prog = L.all_progress(uid())
    skipped = {r["question_id"] for r in db.q("SELECT question_id FROM skipped WHERE user_id=?", (uid(),))}
    revs = {r["question_id"]: r for r in L.reviews(uid())}
    out = []
    kw = (a.get("q") or "").lower()
    for q in L.visible_questions(uid(), sid):
        if a.get("category") and str(q["category_id"]) != a["category"]:
            continue
        if a.get("tier") and str(q["tier"]) != a["tier"]:
            continue
        if a.get("type") and q["type"] != a["type"]:
            continue
        p = prog.get(q["id"], {})
        st = p.get("status", "todo")
        if a.get("status"):
            if a["status"] == "skipped" and q["id"] not in skipped:
                continue
            if a["status"] == "favorite" and not p.get("favorite"):
                continue
            if a["status"] not in ("skipped", "favorite") and st != a["status"]:
                continue
        if kw and kw not in (q["title"] + "".join(q["points"]) + q["source"]).lower():
            continue
        rv = revs.get(q["id"])
        out.append({"id": q["id"], "title": q["title"], "type": q["type"], "category_id": q["category_id"], "tier": q["tier"], "score": q["score"],
                    "points": q["points"], "source": q["source"], "level": (q["extra"] or {}).get("level"), "cls_by": q["cls_by"], "owner_id": q["owner_id"],
                    "status": st, "skipped": q["id"] in skipped, "favorite": p.get("favorite", 0), "review_due": rv["due"] if rv else None})
    out.sort(key=lambda x: (x["tier"], x["score"], x["type"] == "external"))
    return jsonify(out)


@bp.get("/api/questions/<qid>")
@auth()
def question_get(qid):
    q = L.get_question(qid)
    if not q or (q["owner_id"] and q["owner_id"] != uid()):
        return err("题目不存在", 404)
    p = L.progress(uid(), qid)
    reveal = bool((p.get("assist") or {}).get("answer") or (p.get("assist") or {}).get("ref"))
    rv = db.q1("SELECT * FROM reviews WHERE user_id=? AND question_id=?", (uid(), qid))
    att = db.q("SELECT id, mode, score, max_score, detail, independent, created_at, day FROM attempts WHERE user_id=? AND question_id=? ORDER BY id DESC LIMIT 10", (uid(), qid))
    for x in att:
        x["detail"] = db.J(x["detail"], {})
    return jsonify({"question": L.public_question(q, reveal=reveal), "progress": p, "review": rv, "attempts": att,
                    "skipped": bool(db.q1("SELECT 1 FROM skipped WHERE user_id=? AND question_id=?", (uid(), qid))),
                    "lesson_done": L.lesson_done(uid(), q["category_id"]) if q["category_id"] else True})


@bp.post("/api/questions")
@auth()
def question_create():
    b = body()
    item = importer.normalize(b, None)
    if item["problems"] and "缺题面" in item["problems"]:
        return err("题面不能为空")
    item["cls"].update({"category_id": b.get("category_id"), "edited": True})
    ids = importer.save_questions(uid(), [item], source=b.get("source") or "手动录入", private=not b.get("shared") or request.user["role"] != "admin")
    return jsonify({"id": ids[0]})


@bp.put("/api/questions/<qid>")
@auth()
def question_update(qid):
    q = L.get_question(qid)
    if not q:
        return err("题目不存在", 404)
    if (q["owner_id"] is None and request.user["role"] != "admin") or (q["owner_id"] and q["owner_id"] != uid()):
        return err("只能修改自己的题，平台题需要管理员", 403)
    b = body()
    db.run("INSERT OR IGNORE INTO question_versions(question_id, version, snapshot, created_at) VALUES (?,?,?,?)",
           (qid, q["version"], db.dumps(q), time.time()))
    fields = {k: b[k] for k in ("title", "stem", "analysis") if k in b}
    for k in ("options", "answer", "extra", "points"):
        if k in b:
            fields[k] = db.dumps(b[k])
    if not fields:
        return err("没有可修改的内容")
    fields["version"] = q["version"] + 1
    fields["updated_at"] = time.time()
    db.run("UPDATE questions SET %s WHERE id=?" % ", ".join("%s=?" % k for k in fields), (*fields.values(), qid))
    db.audit(uid(), "question.update", qid, {"version": fields["version"]})
    return jsonify({"ok": True, "version": fields["version"]})


@bp.put("/api/questions/<qid>/cls")
@auth()
def question_cls(qid):
    q = L.get_question(qid)
    if not q:
        return err("题目不存在", 404)
    if q["owner_id"] is None and request.user["role"] != "admin":
        return err("平台题的分类需要管理员修改", 403)
    b = body()
    db.run("UPDATE questions SET category_id=?, tier=?, score=?, points=?, cls_by=?, cls_reason=? WHERE id=?",
           (b.get("category_id", q["category_id"]), int(b.get("tier", q["tier"])), int(b.get("score", q["score"])),
            db.dumps(b.get("points", q["points"])), b.get("by", "user"), b.get("reason", q["cls_reason"]), qid))
    db.audit(uid(), "question.classify", qid, b)
    return jsonify({"ok": True})


@bp.post("/api/questions/<qid>/progress")
@auth()
def question_progress(qid):
    b = body()
    kw = {k: b[k] for k in ("status", "note", "tags", "code", "favorite") if k in b}
    p = L.save_progress(uid(), qid, **kw)
    if b.get("status") == "review":
        L.add_review(uid(), qid)
    if b.get("status") == "done":
        L.review_result(uid(), qid, True)
    return jsonify(p)


@bp.post("/api/questions/<qid>/reveal")
@auth()
def question_reveal(qid):
    q = L.get_question(qid)
    if not q:
        return err("题目不存在", 404)
    p = L.progress(uid(), qid)
    a = p["assist"]
    a["answer"] = a.get("answer", 0) + 1
    if q["type"] == "code":
        a["ref"] = 1
    L.save_progress(uid(), qid, assist=a)
    return jsonify(L.public_question(q, reveal=True))


def _check_cases(q, include_hidden):
    return grading.code_cases(q, include_hidden)


@bp.post("/api/questions/<qid>/run")
@auth()
def question_run(qid):
    q = L.get_question(qid)
    b = body()
    cases = _check_cases(q, False)
    r = grading.run_code(b.get("lang", "python"), b.get("code", ""), cases)
    if "results" in r:
        for res, c in zip(r["results"], cases):
            res["input"], res["output"] = c.get("input"), c.get("output")
    p = L.progress(uid(), qid)
    if p["status"] == "todo":
        L.save_progress(uid(), qid, status="doing")
    return jsonify(r)


@bp.post("/api/questions/<qid>/submit")
@auth()
def question_submit(qid):
    q = L.get_question(qid)
    if not q:
        return err("题目不存在", 404)
    b = body()
    idem = b.get("idem") or uuid.uuid4().hex
    dup = db.q1("SELECT * FROM attempts WHERE idem=?", (idem,))
    if dup:
        return jsonify({"attempt_id": dup["id"], "duplicate": True, **db.J(dup["detail"], {})})
    p = L.progress(uid(), qid)
    indep = not L.assisted(p)
    detail = {}
    if q["type"] == "code":
        cases = grading.code_cases(q, True)
        if not cases:
            return err("这道题没有可运行的用例，只能用 AI 检查")
        r = grading.run_code(b.get("lang", "python"), b.get("code", ""), cases)
        if r.get("error"):
            return jsonify({"error_run": r["error"]})
        n = sum(1 for x in r["results"] if x["pass"])
        ratio = n / len(cases)
        first = next((i for i, x in enumerate(r["results"]) if not x["pass"]), None)
        detail = {"passed": n, "total": len(cases), "kinds": grading.kind_summary(r["results"]),
                  "hidden": len(q["extra"].get("hidden") or [])}
        if first is not None:
            c = cases[first]
            detail["first_fail"] = {"input": c.get("input") or json.dumps(c["args"], ensure_ascii=False)[1:-1][:600],
                                    "expect": json.dumps(c.get("expect"), ensure_ascii=False)[:300],
                                    "got": r["results"][first].get("err") or r["results"][first].get("got") or grading.KIND_TXT[r["results"][first]["kind"]]}
        code = p["code"]
        code[b.get("lang", "python")] = b.get("code", "")
        L.save_progress(uid(), qid, code=code)
        answer = {"lang": b.get("lang"), "code": b.get("code", "")[:20000]}
    elif q["type"] == "short":
        try:
            g = agents.grade_short(uid(), q, b.get("answer", ""))
        except Exception as e:
            return jsonify({"pending": True, "message": "AI 评分暂不可用：%s。作答已保存，可稍后重新评分。" % e})
        ratio = g["ratio"]
        detail = {"ai": True, **g}
        answer = b.get("answer", "")
    elif q["type"] == "external":
        return err("外部平台的题请在原网站作答后标记完成")
    else:
        try:
            ratio, detail = grading.grade_objective(q, b.get("answer"))
        except Exception:
            return err("答案格式不对")
        answer = b.get("answer")
    full = ratio >= 0.999
    aid = db.run("""INSERT INTO attempts(user_id, question_id, version, mode, answer, score, max_score, detail, independent, used_hint, viewed_answer, idem, created_at, day)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,date('now','localtime'))""",
                 (uid(), qid, q["version"], "practice", db.dumps(answer), round(ratio, 4), 1, db.dumps(detail), 1 if indep else 0,
                  1 if (p["assist"].get("hint") or p["assist"].get("explain")) else 0, 1 if p["assist"].get("answer") else 0, idem, time.time()))
    if full:
        if p["status"] != "done":
            L.save_progress(uid(), qid, status="done")
        L.review_result(uid(), qid, True)
    else:
        rv = db.q1("SELECT done FROM reviews WHERE user_id=? AND question_id=?", (uid(), qid))
        if not rv or rv["done"]:
            L.add_review(uid(), qid)
        else:
            L.review_result(uid(), qid, False)
        if p["status"] == "done":
            L.save_progress(uid(), qid, status="review")
    rv = db.q1("SELECT due, done FROM reviews WHERE user_id=? AND question_id=?", (uid(), qid))
    out = {"attempt_id": aid, "ratio": ratio, "full": full, "independent": indep, "detail": detail, "review": rv}
    if q["type"] != "code" and q["type"] != "short":
        out["answer"], out["analysis"] = q["answer"], q["analysis"]
        a = p["assist"]
        a["answer"] = a.get("answer", 0) + 1  # answers shown after submit
        L.save_progress(uid(), qid, assist=a)
    return jsonify(out)


AI_ASKS = {
    "hint": "请只给 2–3 条循序渐进的提示，不要给出完整答案或完整代码。",
    "explain": "请完整解析：考点、思路、关键步骤、易错点；编程题给出复杂度和 {lang} 参考实现（核心代码模式，函数名 solve）。",
    "review": "这是我的作答：\n{answer}\n请检查是否正确，指出可能出错的情况，并给出最小修改建议（不要整体重写）。",
    "edge": "请补充 5 个容易被忽略的边界情况（编程题按“输入 → 期望输出 → 考察点”列出）。",
    "similar": "请出一道考察相同知识点、情境不同的新题，给出题面与示例，先不要给答案。",
    "knowledge": "请讲解这道题涉及的知识点：概念、常用方法、典型题型，控制在 10 分钟能读完。",
}


@bp.post("/api/questions/<qid>/ai")
@auth()
def question_ai(qid):
    q = L.get_question(qid)
    b = body()
    kind = b.get("kind", "hint")
    if kind not in AI_ASKS:
        return err("未知的请求类型")
    g = L.ensure_goal(uid())
    if kind in ("hint", "explain", "review", "edge"):
        p = L.progress(uid(), qid)
        a = p["assist"]
        a[kind] = a.get(kind, 0) + 1
        L.save_progress(uid(), qid, assist=a)
    pub = L.public_question(q)
    desc = "题目（%s，L%d）：%s\n%s" % (L.TYPE_NAMES.get(q["type"]), q["tier"], q["title"], q["stem"])
    if q["options"]:
        desc += "\n选项：" + "；".join("%s. %s" % ("ABCDEFGH"[i], o) for i, o in enumerate(q["options"]))
    if q["type"] == "code":
        desc += "\n示例：" + "；".join("%s → %s" % (e["input"], e["output"]) for e in pub["extra"].get("examples", []) if not e.get("doubt"))
    if q["type"] == "external":
        desc += "\n（力扣第 %s 题）" % q["extra"].get("no")
    ask = AI_ASKS[kind].format(lang=g["lang"], answer=b.get("answer", ""))
    model_id = b.get("model_id")

    def go(emit):
        cfg = llm.get_model(model_id, request_user_id) if model_id else llm.model_for(request_user_id, "chat")
        out = llm.chat(cfg, [{"role": "system", "content": "你是学习辅导老师。" + agents.BASE_RULES},
                             {"role": "user", "content": desc + "\n\n" + ask}], on_text=lambda t: emit({"type": "delta", "text": t}),
                       user_id=request_user_id, task="chat")
        return {"model": "%s · %s" % (cfg["name"], cfg["model"]), "content": out["content"]}
    request_user_id = uid()
    return sse(go)


@bp.post("/api/questions/<qid>/feedback")
@auth()
def question_feedback(qid):
    b = body()
    db.run("INSERT INTO feedback(user_id, question_id, kind, text, created_at) VALUES (?,?,?,?,?)", (uid(), qid, b.get("kind", "其它"), b.get("text", "")[:2000], time.time()))
    return jsonify({"ok": True})


@bp.post("/api/skip/<qid>")
@auth()
def skip(qid):
    db.run("INSERT OR REPLACE INTO skipped(user_id, question_id, at) VALUES (?,?,?)", (uid(), qid, L.today()))
    return jsonify({"ok": True})


@bp.delete("/api/skip/<qid>")
@auth()
def unskip(qid):
    db.run("DELETE FROM skipped WHERE user_id=? AND question_id=?", (uid(), qid))
    return jsonify({"ok": True})


# ---------------- lessons ----------------
@bp.get("/api/lessons/<int:cid>")
@auth()
def lesson_get(cid):
    r = db.q1("SELECT * FROM lessons WHERE category_id=?", (cid,))
    c = db.q1("SELECT * FROM categories WHERE id=?", (cid,))
    st = db.q1("SELECT * FROM user_lessons WHERE user_id=? AND category_id=?", (uid(), cid))
    res = db.q("SELECT * FROM resources WHERE user_id=? AND category_id=?", (uid(), cid))
    content = db.J(r["content"], None) if r else None
    if content and content.get("example") and content["example"].get("id"):
        q = L.get_question(content["example"]["id"])
        if q:
            content["example"]["q"] = {"id": q["id"], "title": q["title"], "stem": q["stem"], "tier": q["tier"], "type": q["type"]}
    return jsonify({"category": c, "lesson": content, "status": r["status"] if r else None, "by": r["generated_by"] if r else None,
                    "state": db.J(st["state"], {}) if st else {}, "done_at": st["done_at"] if st else None, "resources": res})


@bp.put("/api/lessons/<int:cid>/state")
@auth()
def lesson_state(cid):
    b = body()
    done = b.pop("done", None)
    cur = db.q1("SELECT * FROM user_lessons WHERE user_id=? AND category_id=?", (uid(), cid))
    state = {**(db.J(cur["state"], {}) if cur else {}), **b}
    done_at = (cur or {}).get("done_at")
    if done:
        done_at = L.today()
    db.run("""INSERT INTO user_lessons(user_id, category_id, state, done_at) VALUES (?,?,?,?)
              ON CONFLICT(user_id, category_id) DO UPDATE SET state=excluded.state, done_at=excluded.done_at""", (uid(), cid, db.dumps(state), done_at))
    return jsonify({"state": state, "done_at": done_at})


@bp.post("/api/lessons/<int:cid>/generate")
@auth()
def lesson_generate(cid):
    try:
        return jsonify({"draft": agents.generate_lesson(uid(), cid)})
    except llm.LLMError as e:
        return err(str(e), 502)
    except Exception as e:
        return err("生成失败：%s" % e, 502)


@bp.put("/api/lessons/<int:cid>")
@auth()
def lesson_save(cid):
    b = body()
    content = b.get("content")
    if not isinstance(content, dict) or not content.get("concepts"):
        return err("课程内容不完整")
    db.run("""INSERT INTO lessons(category_id, content, status, generated_by, updated_at) VALUES (?,?,?,?,?)
              ON CONFLICT(category_id) DO UPDATE SET content=excluded.content, status=excluded.status, generated_by=excluded.generated_by, updated_at=excluded.updated_at""",
           (cid, db.dumps(content), "published", b.get("by", "ai"), time.time()))
    db.audit(uid(), "lesson.save", str(cid), {"by": b.get("by", "ai")})
    return jsonify({"ok": True})


# ---------------- plan, goal, reviews ----------------
@bp.get("/api/plan")
@auth()
def plan():
    p = L.build_plan(uid())
    t = L.today()
    today = next((d for d in p["days"] if d["date"] == t), None)
    revs = L.reviews(uid())
    due = [r for r in revs if r["due"] and r["due"] <= t]
    for r in due:
        q = L.get_question(r["question_id"])
        r["title"] = q["title"] if q else r["question_id"]
        r["tier"] = q["tier"] if q else 2
    log = {r["day"]: r["ms"] for r in db.q("SELECT day, ms FROM study_log WHERE user_id=? ORDER BY day DESC LIMIT 60", (uid(),))}
    att = db.q("SELECT question_id, score, independent FROM attempts WHERE user_id=? AND mode='practice'", (uid(),))
    passed = {a["question_id"] for a in att if a["score"] >= 0.999}
    indep = {a["question_id"] for a in att if a["score"] >= 0.999 and a["independent"]}
    p["goal"] = dict(p["goal"])
    return jsonify({**p, "today": today, "overdue": L.overdue(uid(), p), "tests": L.scheduled_tests(uid(), p), "due_reviews": due,
                    "study": log, "independent_rate": (len(indep) / len(passed)) if passed else None,
                    "last_exam": db.q1("SELECT id, type, result FROM exams WHERE user_id=? AND status='done' ORDER BY id DESC LIMIT 1", (uid(),))})


@bp.put("/api/goal")
@auth()
def goal_update():
    b = body()
    g = L.ensure_goal(uid())
    allowed = ("name", "subject_id", "start_date", "exam_date", "hours", "weekly_day", "monthly_day", "overflow", "include_hard", "intervals", "recent_window", "lang")
    f = {k: (db.dumps(b[k]) if k == "intervals" else b[k]) for k in allowed if k in b}
    if "exam_date" in f or "start_date" in f:
        s, e = f.get("start_date", g["start_date"]), f.get("exam_date", g["exam_date"])
        if e <= s:
            return err("考试日期要晚于开始日期")
    if f:
        db.run("UPDATE goals SET %s WHERE id=?" % ", ".join("%s=?" % k for k in f), (*f.values(), g["id"]))
    return jsonify(L.current_goal(uid()))


@bp.get("/api/reviews")
@auth()
def reviews_list():
    out = []
    for r in L.reviews(uid()):
        q = L.get_question(r["question_id"])
        if q:
            p = L.progress(uid(), q["id"])
            out.append({**r, "title": q["title"], "tier": q["tier"], "type": q["type"], "tags": p["tags"]})
    return jsonify({"items": out, "done_count": db.q1("SELECT COUNT(*) n FROM reviews WHERE user_id=? AND done=1", (uid(),))["n"],
                    "intervals": L.goal_intervals(uid())})


@bp.delete("/api/reviews/<qid>")
@auth()
def reviews_remove(qid):
    db.run("UPDATE reviews SET done=1 WHERE user_id=? AND question_id=?", (uid(), qid))
    return jsonify({"ok": True})


@bp.post("/api/activity")
@auth()
def activity():
    b = body()
    ms = max(0, min(int(b.get("ms", 0)), 120000))
    L.add_study(uid(), ms)
    if b.get("qid"):
        p = L.progress(uid(), b["qid"])
        L.save_progress(uid(), b["qid"], time_ms=p["time_ms"] + ms)
    return jsonify({"ok": True})


# ---------------- exams ----------------
@bp.get("/api/exams")
@auth()
def exams_list():
    p = L.build_plan(uid())
    rows = db.q("SELECT id, type, sched_date, status, created_at, result, paper FROM exams WHERE user_id=? ORDER BY id DESC", (uid(),))
    out = []
    for r in rows:
        pap = db.J(r["paper"], {})
        res = db.J(r["result"], None)
        out.append({"id": r["id"], "type": r["type"], "sched_date": r["sched_date"], "status": r["status"], "created_at": r["created_at"],
                    "total": res and res["total"], "max": pap.get("total"), "pass": pap.get("pass"), "excellent": pap.get("excellent"),
                    "used_min": res and res.get("used_min"), "source": pap.get("source"),
                    "items": [{"title": it["title"], "points": it["points"], **({"score": ri["score"], "kind": ri.get("kind")} if res else {})}
                              for it, ri in zip(pap.get("items", []), (res or {}).get("items", [{}] * len(pap.get("items", []))))]})
    return jsonify({"exams": out, "pending": L.scheduled_tests(uid(), p), "profile": exams.profile_for(p["goal"]["subject_id"])})


@bp.post("/api/exams")
@auth()
def exams_create():
    b = body()
    r = exams.create(uid(), b.get("type", "weekly"), b.get("scope", "learned"), bool(b.get("allow_recent")), b.get("sched_date"), b.get("minutes"))
    return jsonify(r)


@bp.post("/api/exams/ai")
@auth()
def exams_ai():
    """AI writes a fresh paper following the subject's exam profile (no hidden tests; marked as unverified)."""
    b = body()
    g = L.ensure_goal(uid())
    prof = exams.profile_for(g["subject_id"])
    cats = {c["id"]: c["name"] for c in db.q("SELECT id, name FROM categories WHERE subject_id=? AND lesson_only=0", (g["subject_id"],))}
    secs = "\n".join("- %s：%d 题，题型 %s，层级 %s，每题 %s 分" % (s["name"], s["count"], "/".join(s["types"]), "/".join("L%d" % t for t in s["tiers"]), s["points"]) for s in prof["sections"])
    prompt = ("请按下面的试卷结构出一套全新的练习题（不要照搬常见原题），学科背景：%s\n%s\n分类（category 填 id）：%s\n"
              "只输出 JSON 数组，每题格式同导入：{\"type\",\"title\",\"stem\",\"options\",\"answer\",\"analysis\",\"params\",\"examples\":[{\"input\",\"output\",\"args\",\"expect\"}],\"category\",\"tier\"}。答案必须自己验算正确。") % (
        agents._subject_brief(uid())[1], secs, "；".join("%d %s" % kv for kv in cats.items()))
    try:
        arr = agents.json_task(uid(), "import", prompt)
    except Exception as e:
        return err("AI 出题失败：%s" % e, 502)
    items, it_iter = [], [importer.normalize(x, cats) for x in arr if isinstance(x, dict)]
    for s in prof["sections"]:
        pick = [x for x in it_iter if x["type"] in s["types"] and not x["problems"]][:s["count"]]
        for x in pick:
            it_iter.remove(x)
            items.append({"qid": None, "section": s["name"], "points": s["points"], "type": x["type"], "title": x["title"], "stem": x["stem"],
                          "options": x["options"], "answer": x["answer"], "analysis": x["analysis"], "extra": x["extra"], "tier": x["cls"]["tier"],
                          "category_id": x["cls"].get("category_id")})
    if len(items) < sum(s["count"] for s in prof["sections"]):
        return err("AI 出的题不完整（%d 题可用），没有生成试卷，请重试" % len(items), 502)
    for i, it in enumerate(items):
        it["qid"] = "ai-%d" % i
    return jsonify(exams.create(uid(), b.get("type", "weekly"), "ai", True, b.get("sched_date"), b.get("minutes"), items=items, source="ai"))


@bp.get("/api/exams/<int:eid>")
@auth()
def exam_get(eid):
    e = exams.get(uid(), eid)
    if not e:
        return err("测试不存在", 404)
    e["paper"] = exams.public_paper(e["paper"], reveal=(e["status"] == "done"))
    e["now"] = time.time()
    return jsonify(e)


@bp.post("/api/exams/<int:eid>/start")
@auth()
def exam_start(eid):
    e = exams.start(uid(), eid)
    if not e:
        return err("测试不存在", 404)
    e["paper"] = exams.public_paper(e["paper"])
    e["now"] = time.time()
    return jsonify(e)


@bp.put("/api/exams/<int:eid>/answers")
@auth()
def exam_save(eid):
    b = body()
    r = exams.save_answers(uid(), eid, b.get("answers"), b.get("flags"))
    return (err(r["error"], 409) if r.get("error") else jsonify(r))


@bp.post("/api/exams/<int:eid>/run")
@auth()
def exam_selftest(eid):
    e = exams.get(uid(), eid)
    if not e or e["status"] != "running":
        return err("测试不在进行中", 409)
    b = body()
    it = next((x for x in e["paper"]["items"] if x["qid"] == b.get("qid")), None)
    if not it or it["type"] != "code":
        return err("只有编程题可以自测")
    cases = grading.code_cases({"extra": it["extra"]}, include_hidden=False)
    return jsonify(grading.run_code(b.get("lang", "python"), b.get("code", ""), cases))


@bp.post("/api/exams/<int:eid>/submit")
@auth()
def exam_submit(eid):
    e = exams.get(uid(), eid)
    if not e:
        return err("测试不存在", 404)
    b = body()
    if e["status"] == "running" and b.get("answers"):
        exams.save_answers(uid(), eid, b["answers"])
        e = exams.get(uid(), eid)
    e = exams.finish(uid(), e)
    e["paper"] = exams.public_paper(e["paper"], reveal=True)
    return jsonify(e)


@bp.post("/api/exams/<int:eid>/adjust")
@auth()
def exam_adjust(eid):
    b = body()
    if not (b.get("reason") or "").strip():
        return err("请写明调整理由")
    r = exams.adjust(uid(), eid, b.get("qid"), b.get("score", 0), b["reason"])
    return err(r["error"]) if isinstance(r, dict) and r.get("error") else jsonify({"ok": True})


@bp.delete("/api/exams/<int:eid>")
@auth()
def exam_abort(eid):
    db.run("DELETE FROM exams WHERE id=? AND user_id=? AND status IN ('ready','running')", (eid, uid()))
    return jsonify({"ok": True})


@bp.post("/api/exams/skip")
@auth()
def exam_skip():
    g = L.ensure_goal(uid())
    db.run("INSERT OR IGNORE INTO exam_skips(user_id, goal_id, date) VALUES (?,?,?)", (uid(), g["id"], body().get("date")))
    return jsonify({"ok": True})


# ---------------- agents & conversations ----------------
@bp.get("/api/conversations")
@auth()
def conv_list():
    return jsonify(db.q("SELECT * FROM conversations WHERE user_id=? ORDER BY updated_at DESC LIMIT 50", (uid(),)))


@bp.post("/api/conversations")
@auth()
def conv_create():
    b = body()
    ag = b.get("agent") if b.get("agent") in agents.AGENTS else "tutor"
    cid = db.run("INSERT INTO conversations(user_id, agent, title, goal_id, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                 (uid(), ag, b.get("title") or agents.AGENTS[ag]["name"], L.ensure_goal(uid())["id"], time.time(), time.time()))
    return jsonify({"id": cid})


@bp.get("/api/conversations/<int:cid>")
@auth()
def conv_get(cid):
    c = db.q1("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, uid()))
    if not c:
        return err("会话不存在", 404)
    c["messages"] = db.q("SELECT id, role, content, model, status, created_at FROM messages WHERE conv_id=? AND role IN ('user','assistant') ORDER BY id", (cid,))
    r = RUNS.get(cid)
    c["running"] = bool(r and not r["done"])
    return jsonify(c)


@bp.delete("/api/conversations/<int:cid>")
@auth()
def conv_delete(cid):
    if db.q1("SELECT 1 FROM conversations WHERE id=? AND user_id=?", (cid, uid())):
        r = RUNS.get(cid)
        if r and not r["done"]:
            r["stop"].set()
        db.run("DELETE FROM messages WHERE conv_id=?", (cid,))
        db.run("DELETE FROM conversations WHERE id=?", (cid,))
    return jsonify({"ok": True})


# ---- background agent runs: independent of the browser connection ----
RUNS = {}  # conv_id -> run
RUNS_LOCK = threading.Lock()


def _start_run(user_id, cid, fn):
    run = {"user_id": user_id, "conv_id": cid, "events": [], "done": False, "stop": threading.Event(), "cond": threading.Condition(), "started": time.time()}
    with RUNS_LOCK:
        old = RUNS.get(cid)
        if old and not old["done"]:
            return None
        RUNS[cid] = run

    def emit(ev):
        with run["cond"]:
            run["events"].append(ev)
            run["cond"].notify_all()

    def worker():
        try:
            res = fn(emit, run["stop"].is_set)
            emit({"type": "done", **(res or {})})
        except llm.Cancelled:
            emit({"type": "stopped"})
        except llm.LLMError as e:
            emit({"type": "error", "message": str(e), "code": e.code, "retryable": e.retryable})
        except Exception as e:
            emit({"type": "error", "message": "出错了：%s" % e})
        with run["cond"]:
            run["done"] = True
            run["finished"] = time.time()
            run["cond"].notify_all()
    threading.Thread(target=worker, daemon=True).start()
    return run


def _attach(run, start=0):
    """Stream a run's events from index `start`. Closing the connection only detaches; the run keeps going."""
    def gen():
        i = start
        yield "event: open\ndata: {}\n\n"
        while True:
            with run["cond"]:
                while i >= len(run["events"]) and not run["done"]:
                    run["cond"].wait(timeout=15)
                    if i >= len(run["events"]) and not run["done"]:
                        break
                batch = run["events"][i:]
                finished = run["done"] and i + len(batch) >= len(run["events"])
            if not batch and not finished:
                yield ": ping\n\n"
                continue
            for ev in batch:
                i += 1
                yield "data: %s\n\n" % json.dumps({**ev, "seq": i}, ensure_ascii=False)
            if finished:
                break
    return Response(gen(), mimetype="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _conv_or_404(cid):
    return db.q1("SELECT * FROM conversations WHERE id=? AND user_id=?", (cid, uid()))


@bp.post("/api/conversations/<int:cid>/send")
@auth()
def conv_send(cid):
    c = _conv_or_404(cid)
    if not c:
        return err("会话不存在", 404)
    b = body()
    text = (b.get("text") or "").strip()
    if not text:
        return err("内容不能为空")
    user_id = uid()
    if db.q1("SELECT 1 FROM exams WHERE user_id=? AND status='running'", (user_id,)):
        return err("测试进行中，AI 助手已关闭。交卷后再使用。", 409)
    if not db.q1("SELECT 1 FROM messages WHERE conv_id=?", (cid,)):
        db.run("UPDATE conversations SET title=? WHERE id=?", (text[:24], cid))
    run = _start_run(user_id, cid, lambda emit, stop: agents.run_agent(user_id, c["agent"], cid, text, b.get("model_id"), emit, b.get("context", ""), stop))
    if not run:
        return err("上一条回复还在生成，等它结束或先点「停止」", 409)
    return _attach(run)


@bp.post("/api/conversations/<int:cid>/regenerate")
@auth()
def conv_regen(cid):
    c = _conv_or_404(cid)
    last = db.q1("SELECT id, content FROM messages WHERE conv_id=? AND role='user' ORDER BY id DESC LIMIT 1", (cid,))
    if not last or not c:
        return err("没有可以重新生成的消息")
    with RUNS_LOCK:
        r = RUNS.get(cid)
        if r and not r["done"]:
            return err("回复还在生成，先点「停止」", 409)
    db.run("DELETE FROM messages WHERE conv_id=? AND id>?", (cid, last["id"]))
    user_id = uid()
    b = body()
    run = _start_run(user_id, cid, lambda emit, stop: agents.run_agent(user_id, c["agent"], cid, last["content"], b.get("model_id"), emit, "", stop, save_user=False))
    return _attach(run)


@bp.get("/api/conversations/<int:cid>/attach")
@auth()
def conv_attach(cid):
    if not _conv_or_404(cid):
        return err("会话不存在", 404)
    r = RUNS.get(cid)
    if not r:
        return err("没有正在生成的回复", 404)
    return _attach(r, int(request.args.get("from", 0)))


@bp.post("/api/conversations/<int:cid>/stop")
@auth()
def conv_stop(cid):
    if not _conv_or_404(cid):
        return err("会话不存在", 404)
    r = RUNS.get(cid)
    if r and not r["done"]:
        r["stop"].set()
    return jsonify({"ok": True})


@bp.get("/api/runs")
@auth()
def runs_active():
    return jsonify([{"conv_id": k, "started": r["started"]} for k, r in list(RUNS.items()) if r["user_id"] == uid() and not r["done"]])


@bp.get("/api/proposals")
@auth()
def proposals():
    rows = db.q("SELECT * FROM proposals WHERE user_id=? AND status=? ORDER BY id DESC", (uid(), request.args.get("status", "pending")))
    for r in rows:
        r["payload"] = db.J(r["payload"], {})
    return jsonify(rows)


@bp.post("/api/proposals/<int:pid>")
@auth()
def proposal_decide(pid):
    r = agents.apply_proposal(uid(), pid, bool(body().get("accept")))
    return err(r["error"]) if r.get("error") else jsonify(r)


# ---------------- models ----------------
@bp.get("/api/models")
@auth()
def models_list():
    ms = db.q("SELECT * FROM model_configs WHERE owner_id IS NULL OR owner_id=? ORDER BY id", (uid(),))
    routes = {r["task"]: r["model_id"] for r in db.q("SELECT * FROM task_routes WHERE user_id=?", (uid(),))}
    return jsonify({"models": [llm.public_model(m) for m in ms], "presets": llm.PRESETS, "tasks": llm.TASKS, "routes": routes})


@bp.post("/api/models")
@auth()
def model_create():
    b = body()
    pre = next((p for p in llm.PRESETS if p["key"] == b.get("preset")), llm.PRESETS[-1])
    caps = {**pre["caps"], **(b.get("caps") or {})}
    owner = None if (b.get("shared") and request.user["role"] == "admin") else uid()
    url = (b.get("base_url") or pre["base_url"]).strip()
    if not url.startswith(("http://", "https://")):
        return err("API 地址要以 http:// 或 https:// 开头")
    mid = db.run("""INSERT INTO model_configs(owner_id, name, provider, base_url, model, api_key, timeout, max_tokens, caps, enabled, price_in, price_out, price_note, created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?)""",
                 (owner, b.get("name") or pre["name"], b.get("provider") or pre["provider"], url, b.get("model") or pre["model"],
                  b.get("api_key", ""), int(b.get("timeout") or 60), int(b.get("max_tokens") or 4096), db.dumps(caps),
                  b.get("price_in"), b.get("price_out"), b.get("price_note"), time.time()))
    db.audit(uid(), "model.create", str(mid), {"name": b.get("name") or pre["name"], "provider": pre["provider"]})
    return jsonify({"id": mid})


@bp.put("/api/models/<int:mid>")
@auth()
def model_update(mid):
    m = llm.get_model(mid, uid())
    if not m or (m["owner_id"] is None and request.user["role"] != "admin"):
        return err("没有权限", 403)
    b = body()
    f = {k: b[k] for k in ("name", "base_url", "model", "timeout", "max_tokens", "enabled", "price_in", "price_out", "price_note") if k in b}
    if b.get("api_key"):
        f["api_key"] = b["api_key"]
    if "caps" in b:
        f["caps"] = db.dumps(b["caps"])
    if f:
        db.run("UPDATE model_configs SET %s WHERE id=?" % ", ".join("%s=?" % k for k in f), (*f.values(), mid))
        db.audit(uid(), "model.update", str(mid), {k: v for k, v in f.items() if k != "api_key"} | ({"api_key": "已更换"} if "api_key" in f else {}))
    return jsonify({"ok": True})


@bp.delete("/api/models/<int:mid>")
@auth()
def model_delete(mid):
    m = llm.get_model(mid, uid())
    if not m or (m["owner_id"] is None and request.user["role"] != "admin"):
        return err("没有权限", 403)
    db.run("DELETE FROM model_configs WHERE id=?", (mid,))
    db.run("DELETE FROM task_routes WHERE model_id=?", (mid,))
    db.audit(uid(), "model.delete", str(mid))
    return jsonify({"ok": True})


@bp.post("/api/models/<int:mid>/test")
@auth()
def model_test(mid):
    m = llm.get_model(mid, uid())
    if not m:
        return err("模型不存在", 404)
    t0 = time.time()
    try:
        out = llm.chat(m, [{"role": "user", "content": "只回复“连接正常”四个字。"}], max_tokens=20, user_id=uid(), task="test")
        res = {"ok": True, "reply": out["content"][:60], "ms": int((time.time() - t0) * 1000)}
        if db.J(m["caps"], {}).get("tools"):
            try:
                tool = {"name": "ping", "description": "连通性测试，必须调用一次", "parameters": {"type": "object", "properties": {"ok": {"type": "boolean"}}}}
                o2 = llm.chat(m, [{"role": "user", "content": "请调用 ping 工具。"}], tools=[tool], max_tokens=60, user_id=uid(), task="test")
                res["tools"] = bool(o2["tool_calls"])
            except llm.LLMError as e:
                res["tools"] = False
                res["tools_error"] = str(e)
        return jsonify(res)
    except llm.LLMError as e:
        return jsonify({"ok": False, "error": str(e), "code": e.code})


@bp.put("/api/routes")
@auth()
def routes_set():
    for task, mid in (body() or {}).items():
        if task in llm.TASKS:
            if mid:
                db.run("INSERT OR REPLACE INTO task_routes(user_id, task, model_id) VALUES (?,?,?)", (uid(), task, int(mid)))
            else:
                db.run("DELETE FROM task_routes WHERE user_id=? AND task=?", (uid(), task))
    return jsonify({"ok": True})


@bp.get("/api/usage")
@auth()
def usage():
    days = int(request.args.get("days", 30))
    rows = db.q("""SELECT u.model_id, m.name, m.model, m.price_in, m.price_out, m.price_note, u.task, u.status, COUNT(*) n,
                          SUM(COALESCE(prompt_tokens,0)) pin, SUM(COALESCE(completion_tokens,0)) pout, AVG(latency_ms) lat,
                          SUM(CASE WHEN prompt_tokens IS NULL THEN 1 ELSE 0 END) unknown
                   FROM usage u LEFT JOIN model_configs m ON m.id=u.model_id
                   WHERE u.user_id=? AND u.created_at>? GROUP BY u.model_id, u.task, u.status ORDER BY n DESC""", (uid(), time.time() - days * 86400))
    for r in rows:
        if r["price_in"] is not None and r["price_out"] is not None:
            r["cost"] = round((r["pin"] * r["price_in"] + r["pout"] * r["price_out"]) / 1e6, 4)
        else:
            r["cost"] = None
    return jsonify(rows)


@bp.post("/api/compare")
@auth()
def compare():
    b = body()
    out = []
    for mid in (b.get("model_ids") or [])[:4]:
        m = llm.get_model(int(mid), uid())
        if not m:
            continue
        t0 = time.time()
        try:
            r = llm.chat(m, [{"role": "user", "content": b.get("prompt", "")}], user_id=uid(), task="compare")
            out.append({"model": "%s · %s" % (m["name"], m["model"]), "content": r["content"], "ms": int((time.time() - t0) * 1000), "usage": r["usage"]})
        except llm.LLMError as e:
            out.append({"model": "%s · %s" % (m["name"], m["model"]), "error": str(e), "ms": int((time.time() - t0) * 1000)})
    return jsonify(out)


# ---------------- import & classify jobs ----------------
@bp.post("/api/import/extract")
@auth()
def import_extract():
    f = request.files.get("file")
    if not f:
        return err("没有收到文件")
    data = f.read()
    if len(data) > 20 * 1024 * 1024:
        return err("文件超过 20 MB")
    try:
        return jsonify({"text": importer.extract_text(f.filename, data), "name": f.filename})
    except Exception as e:
        return err(str(e))


@bp.post("/api/jobs/import")
@auth()
def job_import():
    b = body()
    text = (b.get("text") or "").strip()
    if not text:
        return err("先粘贴内容或选择文件")
    user_id, sid = uid(), b.get("subject_id") or L.ensure_goal(uid())["subject_id"]
    titles = {r["title"].strip() for r in db.q("SELECT title FROM questions WHERE subject_id=?", (sid,))}

    def fn(progress, stop):
        items = importer.parse(user_id, sid, text, progress, stop)
        for it in items:
            it["dup"] = it["title"].strip() in titles
            it["include"] = not it["dup"] and not it["problems"]
        return items
    return jsonify(job_view(start_job(user_id, "import", fn)))


@bp.post("/api/jobs/classify")
@auth()
def job_classify():
    b = body()
    user_id = uid()
    g = L.ensure_goal(user_id)
    scope = b.get("scope", "default")
    qs = [q for q in L.visible_questions(user_id, g["subject_id"]) if scope == "all" or (scope == "default" and q["cls_by"] == "default")
          or (scope == "mine" and q["owner_id"] == user_id) or (scope == q["type"])]
    if not qs:
        return err("这个范围里没有题")

    def fn(progress, stop):
        res = agents.classify(user_id, g["subject_id"], qs, progress, stop)
        return res
    j = start_job(user_id, "classify", fn)
    j["total"] = len(qs)
    return jsonify(job_view(j))


@bp.get("/api/jobs/<jid>")
@auth()
def job_get(jid):
    j = JOBS.get(jid)
    if not j or j["user_id"] != uid():
        return err("任务不存在", 404)
    return jsonify(job_view(j))


@bp.post("/api/jobs/<jid>/cancel")
@auth()
def job_cancel(jid):
    j = JOBS.get(jid)
    if j and j["user_id"] == uid():
        j["cancel"] = True
    return jsonify({"ok": True})


@bp.post("/api/import/save")
@auth()
def import_save():
    b = body()
    items = [x for x in b.get("items") or [] if x.get("include")]
    if not items:
        return err("没有勾选任何题")
    ids = importer.save_questions(uid(), items, source=(b.get("source") or "导入")[:40], private=not (b.get("shared") and request.user["role"] == "admin"))
    return jsonify({"ids": ids})


@bp.post("/api/classify/apply")
@auth()
def classify_apply():
    res = body().get("results") or {}
    n = 0
    for qid, c in res.items():
        q = L.get_question(qid)
        if not q or (q["owner_id"] is None and request.user["role"] != "admin") or (q["owner_id"] and q["owner_id"] != uid()):
            continue
        db.run("UPDATE questions SET category_id=?, tier=?, score=?, points=?, cls_by='ai', cls_reason=? WHERE id=?",
               (c["category_id"], int(c["tier"]), int(c["score"]), db.dumps(c.get("points") or []), c.get("reason", ""), qid))
        n += 1
    db.audit(uid(), "questions.classify", "batch", {"count": n})
    return jsonify({"applied": n})


# ---------------- resources ----------------
@bp.get("/api/resources/search")
@auth()
def resources_search():
    qtext = (request.args.get("q") or "").strip()
    if not qtext:
        return err("请输入关键词")
    out = {"links": agents.search_links(qtext), "results": [], "sources": []}
    try:
        yt = agents.youtube_search(qtext)
        if yt is None:
            out["sources"].append({"name": "YouTube 接口", "status": "未配置（在设置里填写 YouTube Data API Key 可直接显示视频列表）"})
        else:
            out["results"] += yt
            out["sources"].append({"name": "YouTube 接口", "status": "正常", "count": len(yt)})
    except Exception as e:
        out["sources"].append({"name": "YouTube 接口", "status": "失败：%s" % str(e)[:80], "retry": True})
    seen, uniq = set(), []
    for r in out["results"]:
        if r["url"] not in seen:
            seen.add(r["url"])
            uniq.append(r)
    out["results"] = uniq
    return jsonify(out)


@bp.get("/api/resources")
@auth()
def resources_list():
    return jsonify(db.q("SELECT * FROM resources WHERE user_id=? ORDER BY id DESC", (uid(),)))


@bp.post("/api/resources")
@auth()
def resources_add():
    b = body()
    if not str(b.get("url", "")).startswith(("http://", "https://")):
        return err("链接无效")
    db.run("INSERT OR REPLACE INTO resources(user_id, title, url, platform, meta, category_id, created_at) VALUES (?,?,?,?,?,?,?)",
           (uid(), b.get("title", b["url"])[:200], b["url"], b.get("platform", ""), db.dumps(b.get("meta") or {}), b.get("category_id"), time.time()))
    return jsonify({"ok": True})


@bp.delete("/api/resources/<int:rid>")
@auth()
def resources_del(rid):
    db.run("DELETE FROM resources WHERE id=? AND user_id=?", (rid, uid()))
    return jsonify({"ok": True})


@bp.put("/api/settings/youtube_key")
@auth(admin=True)
def youtube_key():
    db.run("INSERT OR REPLACE INTO meta(k, v) VALUES ('youtube_key', ?)", (body().get("key", ""),))
    return jsonify({"ok": True})


# ---------------- data export / import (cross-device) ----------------
USER_TABLES = ["progress", "attempts", "reviews", "goals", "skipped", "exams", "exam_skips", "study_log", "user_lessons", "resources", "proposals"]


@bp.get("/api/export")
@auth()
def export():
    data = {"version": VERSION, "exported_at": time.time(), "tables": {}}
    for t in USER_TABLES:
        data["tables"][t] = db.q("SELECT * FROM %s WHERE user_id=?" % t, (uid(),))
    data["questions"] = db.q("SELECT * FROM questions WHERE owner_id=?", (uid(),))
    data["conversations"] = db.q("SELECT * FROM conversations WHERE user_id=?", (uid(),))
    data["messages"] = db.q("SELECT m.* FROM messages m JOIN conversations c ON c.id=m.conv_id WHERE c.user_id=?", (uid(),))
    return Response(json.dumps(data, ensure_ascii=False), mimetype="application/json",
                    headers={"Content-Disposition": "attachment; filename=studyagent-backup-%s.json" % L.today()})


@bp.post("/api/import-data")
@auth()
def import_data():
    f = request.files.get("file")
    try:
        data = json.loads(f.read().decode("utf-8")) if f else body()
    except Exception:
        return err("备份文件格式不对")
    n = 0
    with db.tx() as c:
        for q in data.get("questions") or []:
            q["owner_id"] = uid()
            cols = list(q.keys())
            c.execute("INSERT OR REPLACE INTO questions(%s) VALUES (%s)" % (",".join(cols), ",".join("?" * len(cols))), [q[k] for k in cols])
        for t in USER_TABLES:
            for r in (data.get("tables") or {}).get(t, []):
                r = dict(r)
                r["user_id"] = uid()
                if t in ("attempts", "goals", "exams", "resources", "proposals"):
                    r.pop("id", None)
                cols = list(r.keys())
                c.execute("INSERT OR REPLACE INTO %s(%s) VALUES (%s)" % (t, ",".join(cols), ",".join("?" * len(cols))), [r[k] for k in cols])
                n += 1
    db.audit(uid(), "data.import", "backup", {"rows": n})
    return jsonify({"rows": n})


@bp.get("/api/system")
@auth()
def system():
    port = request.host.split(":")[-1] if ":" in request.host else "80"
    from . import config
    return jsonify({"version": VERSION, "data_dir": db.DATA_DIR, "lan": lan_addresses(port), "languages": grading.languages(),
                    "lan_config": config.load()["lan"], "lan_running": lan_running(), "lan_restart": lan_restart_needed(), "desktop": os.environ.get("SA_DESKTOP") == "1", "os": sys.platform, "local": request.remote_addr in ("127.0.0.1", "::1"),
                    "youtube": bool((db.q1("SELECT v FROM meta WHERE k='youtube_key'") or {}).get("v"))})


@bp.put("/api/settings/lan")
@auth(admin=True)
def lan_setting():
    from . import config
    c = config.save(lan=bool(body().get("lan")))
    db.audit(uid(), "settings.lan", str(c["lan"]))
    return jsonify({"lan": c["lan"], "running": lan_running(), "restart_needed": lan_restart_needed()})


@bp.get("/api/ping")
def ping():
    """Unauthenticated reachability check for the phone app's connect page (cross-origin allowed)."""
    r = jsonify({"app": "StudyAgent", "version": VERSION, "lan": lan_running()})
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Cache-Control"] = "no-store"
    return r


@bp.post("/api/settings/firewall")
@auth(admin=True)
def firewall_setting():
    if request.remote_addr not in ("127.0.0.1", "::1"):
        return err("只能在运行 StudyAgent 的电脑上设置防火墙", 403)
    from . import netfix
    port = request.host.split(":")[-1] if ":" in request.host else "8765"
    r = netfix.allow_windows_firewall(port)
    db.audit(uid(), "settings.firewall", "ok" if r["ok"] else "fail")
    return jsonify(r)


@bp.get("/api/docs")
def docs():
    from flask import current_app
    rows = sorted({(r.rule, ",".join(sorted(m for m in r.methods if m in ("GET", "POST", "PUT", "DELETE")))) for r in current_app.url_map.iter_rules() if r.rule.startswith("/api/")})
    return jsonify({"auth": "请求头 Authorization: Bearer <访问码>", "endpoints": [{"path": p, "methods": m} for p, m in rows]})


# ---------------- web client ----------------
@bp.get("/")
def index():
    return send_from_directory(WEB, "index.html")


@bp.get("/sw.js")
def service_worker():
    r = send_from_directory(WEB, "sw.js")
    r.headers["Service-Worker-Allowed"] = "/"
    r.headers["Cache-Control"] = "no-cache"
    return r


@bp.get("/web/<path:p>")
def web(p):
    return send_from_directory(WEB, p)
