"""Questions, progress, spaced review, study plan."""
import calendar
import datetime as dt
import time

from . import db

TIER_NAMES = {1: "入门", 2: "基础", 3: "进阶", 4: "挑战"}
TIER_DESC = {1: "单一知识点，按题意直接实现", 2: "套用一个标准方法或模板", 3: "组合两种方法，或边界、规则较复杂", 4: "综合性强，需要较深的分析或设计"}
TYPE_NAMES = {"single": "单选", "multi": "多选", "judge": "判断", "fill": "填空", "short": "简答", "code": "编程", "external": "外部题"}
MIN_PER_TYPE = {"single": 3, "judge": 2, "multi": 4, "fill": 4, "short": 12, "code": 30, "external": 30}


def today():
    return dt.date.today().isoformat()


def add_days(s, n):
    return (dt.date.fromisoformat(s) + dt.timedelta(days=n)).isoformat()


def diff_days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def row_q(r, full=True):
    if not r:
        return None
    q = dict(r)
    for k, d in (("options", []), ("answer", None), ("extra", {}), ("points", [])):
        q[k] = db.J(q.get(k), d)
    return q


def get_question(qid):
    return row_q(db.q1("SELECT * FROM questions WHERE id=?", (qid,)))


def visible_questions(user_id, subject_id=None):
    sql = "SELECT * FROM questions WHERE status='published' AND (owner_id IS NULL OR owner_id=?)"
    args = [user_id]
    if subject_id:
        sql += " AND subject_id=?"
        args.append(subject_id)
    return [row_q(r) for r in db.q(sql, args)]


def cost(q):
    base = MIN_PER_TYPE.get(q["type"], 10)
    if q["type"] in ("code", "external"):
        return [0, 25, 35, 45, 60][q["tier"]]
    return int(base * (0.8 + 0.2 * q["tier"]))


def public_question(q, reveal=False):
    """Strip answers / hidden tests / reference unless revealed."""
    out = {k: q[k] for k in ("id", "subject_id", "category_id", "type", "title", "stem", "options", "tier", "score", "points",
                             "source", "source_ref", "cls_by", "cls_reason", "verified", "version", "owner_id", "status")}
    ex = q["extra"] or {}
    out["extra"] = {k: ex[k] for k in ("params", "url", "no", "level", "orig_category", "pdf_src", "fill_rules", "blanks", "rubric_points") if k in ex}
    if q["type"] == "code":
        out["extra"]["examples"] = [{k: e.get(k) for k in ("input", "output", "note", "doubt")} | {"runnable": isinstance(e.get("args"), list) and "expect" in e}
                                    for e in ex.get("examples") or []]
        out["extra"]["hidden_count"] = len(ex.get("hidden") or [])
        out["extra"]["has_ref"] = bool(ex.get("ref"))
    if reveal:
        out["answer"] = q["answer"]
        out["analysis"] = q["analysis"]
        if q["type"] == "code" and ex.get("ref"):
            out["extra"]["ref"] = ex["ref"]
        if q["type"] == "short":
            out["extra"]["rubric"] = ex.get("rubric")
    return out


# ---------------- progress ----------------
def progress(user_id, qid):
    r = db.q1("SELECT * FROM progress WHERE user_id=? AND question_id=?", (user_id, qid))
    if not r:
        return {"status": "todo", "note": "", "tags": [], "time_ms": 0, "assist": {}, "code": {}, "done_at": None, "favorite": 0}
    r = dict(r)
    for k, d in (("tags", []), ("assist", {}), ("code", {})):
        r[k] = db.J(r[k], d)
    return r


def save_progress(user_id, qid, **kw):
    p = progress(user_id, qid)
    p.update(kw)
    if p.get("status") == "done" and not p.get("done_at"):
        p["done_at"] = today()
    db.run("""INSERT INTO progress(user_id, question_id, status, note, tags, time_ms, assist, code, done_at, favorite)
              VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id, question_id) DO UPDATE SET status=excluded.status, note=excluded.note,
              tags=excluded.tags, time_ms=excluded.time_ms, assist=excluded.assist, code=excluded.code, done_at=excluded.done_at, favorite=excluded.favorite""",
           (user_id, qid, p["status"], p["note"], db.dumps(p["tags"]), p["time_ms"], db.dumps(p["assist"]), db.dumps(p["code"]), p["done_at"], p.get("favorite", 0)))
    return p


def all_progress(user_id):
    out = {}
    for r in db.q("SELECT question_id, status, done_at, tags, assist, favorite FROM progress WHERE user_id=?", (user_id,)):
        out[r["question_id"]] = {"status": r["status"], "done_at": r["done_at"], "tags": db.J(r["tags"], []), "assisted": bool(db.J(r["assist"], {})), "favorite": r["favorite"]}
    return out


def assisted(p):
    a = p.get("assist") or {}
    return any(a.get(k) for k in ("hint", "explain", "review", "ref", "answer", "edge"))


# ---------------- spaced review ----------------
def goal_intervals(user_id):
    g = current_goal(user_id)
    return db.J(g["intervals"], [1, 3, 7, 14]) if g else [1, 3, 7, 14]


def add_review(user_id, qid, reset=True):
    iv = goal_intervals(user_id)
    r = db.q1("SELECT * FROM reviews WHERE user_id=? AND question_id=?", (user_id, qid))
    due = add_days(today(), iv[0] if iv else 1)
    if r and not r["done"] and not reset:
        return
    db.run("""INSERT INTO reviews(user_id, question_id, stage, due, done, history, added) VALUES (?,?,?,?,0,?,?)
              ON CONFLICT(user_id, question_id) DO UPDATE SET stage=0, due=excluded.due, done=0""",
           (user_id, qid, 0, due, db.dumps(db.J(r["history"], []) if r else []), today()))


def review_result(user_id, qid, ok):
    r = db.q1("SELECT * FROM reviews WHERE user_id=? AND question_id=?", (user_id, qid))
    if not r or r["done"]:
        if not ok and (not r or r["done"]):
            add_review(user_id, qid)
        return
    if r["due"] and r["due"] > today():
        return  # not due yet, does not count as a review
    hist = db.J(r["history"], [])
    hist.append({"d": today(), "ok": ok})
    iv = goal_intervals(user_id)
    stage = r["stage"]
    if ok:
        stage += 1
        done = stage >= len(iv)
        due = None if done else add_days(today(), iv[stage])
    else:
        stage, done, due = 0, False, add_days(today(), iv[0] if iv else 1)
    db.run("UPDATE reviews SET stage=?, due=?, done=?, history=? WHERE user_id=? AND question_id=?",
           (stage, due, 1 if done else 0, db.dumps(hist), user_id, qid))


def reviews(user_id, include_done=False):
    rows = db.q("SELECT * FROM reviews WHERE user_id=?" + ("" if include_done else " AND done=0") + " ORDER BY due", (user_id,))
    for r in rows:
        r["history"] = db.J(r["history"], [])
    return rows


# ---------------- goals & plan ----------------
def current_goal(user_id):
    return db.q1("SELECT * FROM goals WHERE user_id=? AND status='active' ORDER BY current DESC, id DESC LIMIT 1", (user_id,))


def ensure_goal(user_id):
    g = current_goal(user_id)
    if g:
        return g
    sub = db.q1("SELECT id, name FROM subjects ORDER BY id LIMIT 1")
    db.run("""INSERT INTO goals(user_id, subject_id, name, start_date, exam_date, created_at) VALUES (?,?,?,?,?,?)""",
           (user_id, sub["id"] if sub else None, (sub["name"] if sub else "学习") + "备考", today(), add_days(today(), 42), time.time()))
    return current_goal(user_id)


def lesson_done(user_id, cat_id):
    r = db.q1("SELECT done_at FROM user_lessons WHERE user_id=? AND category_id=?", (user_id, cat_id))
    return bool(r and r["done_at"])


def _event_for(goal, date, idx, total):
    if idx == total - 1:
        return "monthly"
    d = dt.date.fromisoformat(date)
    last = calendar.monthrange(d.year, d.month)[1]
    if d.day == min(int(goal["monthly_day"] or 31), last):
        return "monthly"
    if (d.isoweekday() % 7) == int(goal["weekly_day"] or 0):  # 0 = Sunday
        return "weekly"
    return None


def build_plan(user_id, goal=None):
    g = goal or ensure_goal(user_id)
    start, end = g["start_date"], g["exam_date"]
    total = max(1, diff_days(start, end))
    budget = round(float(g["hours"] or 1.5) * 60)
    sprint = max(3, round(total * 0.15)) if total >= 14 else 0
    learn_days = total - sprint
    evs = {}
    for d in range(total):
        e = _event_for(g, add_days(start, d), d, total)
        if e:
            evs[d] = e
    cats = db.q("SELECT * FROM categories WHERE subject_id=? AND enabled=1 ORDER BY sort, id", (g["subject_id"],))
    lessons = {r["category_id"]: db.J(r["content"], {}) for r in db.q(
        "SELECT category_id, content FROM lessons WHERE status='published' AND category_id IN (SELECT id FROM categories WHERE subject_id=?)", (g["subject_id"],))}
    prog = all_progress(user_id)
    skipped = {r["question_id"] for r in db.q("SELECT question_id FROM skipped WHERE user_id=?", (user_id,))}
    qs = [q for q in visible_questions(user_id, g["subject_id"])
          if q["id"] not in skipped and not (prog.get(q["id"], {}).get("status") == "done" and (prog[q["id"]].get("done_at") or "") < start)]

    def rank(q):
        if q["verified"] and q["type"] != "external":
            return 1
        return 1 + min(3, q["tier"])
    cands = [q for q in qs if g["include_hard"] or q["tier"] < 4 or rank(q) == 1]
    cap = sum((max(0, budget - 150) if evs.get(d) else budget) for d in range(learn_days))
    intro = sum(int(lessons[c["id"]].get("minutes", 30)) for c in cats if c["id"] in lessons and not lesson_done(user_id, c["id"]))
    need = sum(cost(q) for q in cands) + intro
    over = max(0, need - cap)
    chosen = {q["id"] for q in cands}
    trimmed = []
    mode = (g["overflow"] or "trim") if over > 0 else "none"
    if mode == "trim":
        cut = 0
        for q in sorted(cands, key=lambda q: (-rank(q), -cost(q))):
            if cut >= over or rank(q) == 1:
                break
            chosen.discard(q["id"])
            trimmed.append(q["id"])
            cut += cost(q)
    seq = []
    for c in cats:
        if c["id"] in lessons and not lesson_done(user_id, c["id"]):
            seq.append({"type": "learn", "category_id": c["id"], "name": c["name"], "cost": int(lessons[c["id"]].get("minutes", 30))})
        cq = sorted([q for q in cands if q["category_id"] == c["id"] and q["id"] in chosen],
                    key=lambda q: (q["tier"], q["score"], q["type"] == "external"))
        seq += [{"type": "q", "id": q["id"], "title": q["title"], "tier": q["tier"], "qtype": q["type"], "cost": cost(q)} for q in cq]
    orphan = [q for q in cands if q["id"] in chosen and q["category_id"] not in {c["id"] for c in cats}]
    seq += [{"type": "q", "id": q["id"], "title": q["title"], "tier": q["tier"], "qtype": q["type"], "cost": cost(q)} for q in sorted(orphan, key=lambda q: q["tier"])]
    days, i = [], 0
    for d in range(total):
        date = add_days(start, d)
        day = {"date": date, "idx": d, "tasks": [], "ev": evs.get(d), "sprint": d >= learn_days}
        left = max(0, budget - 150) if day["ev"] else budget
        if not day["sprint"]:
            while i < len(seq) and left > 0 and (left >= seq[i]["cost"] * 0.7 or not day["tasks"]):
                day["tasks"].append(seq[i])
                left -= seq[i]["cost"]
                i += 1
        days.append(day)
    sprint_days = [d for d in days if d["sprint"]]
    k = 0
    while i < len(seq):
        tgt = sprint_days[k % len(sprint_days)] if sprint_days else days[-1]
        tgt["tasks"].append(seq[i])
        i += 1
        k += 1
    for d in sprint_days:
        if not d["tasks"]:
            d["tasks"].append({"type": "review", "cost": budget})
    for d in days:
        d["load"] = sum(t["cost"] for t in d["tasks"] if t["type"] != "review") + (150 if d["ev"] else 0)
        d["overload"] = max(0, d["load"] - budget)
    return {"goal": g, "days": days, "total": total, "budget": budget, "sprint": sprint, "need": need, "cap": cap, "over": over,
            "mode": mode, "trimmed": trimmed, "chosen": len(chosen),
            "suggest_hours": (round((need / max(1, total - sprint)) / 30 + 0.4999) / 2) if over else None}


def overdue(user_id, plan):
    t = today()
    prog = all_progress(user_id)
    out = []
    for d in plan["days"]:
        if d["date"] >= t:
            break
        for x in d["tasks"]:
            if x["type"] == "q" and prog.get(x["id"], {}).get("status") != "done":
                out.append({**x, "date": d["date"]})
    return out


def scheduled_tests(user_id, plan):
    g = plan["goal"]
    t = today()
    done = {r["sched_date"] for r in db.q("SELECT sched_date FROM exams WHERE user_id=? AND goal_id=? AND sched_date IS NOT NULL", (user_id, g["id"]))}
    skips = {r["date"] for r in db.q("SELECT date FROM exam_skips WHERE user_id=? AND goal_id=?", (user_id, g["id"]))}
    return [{"date": d["date"], "type": d["ev"]} for d in plan["days"] if d["ev"] and d["date"] <= t and d["date"] not in done and d["date"] not in skips]


def add_study(user_id, ms):
    db.run("INSERT INTO study_log(user_id, day, ms) VALUES (?,?,?) ON CONFLICT(user_id, day) DO UPDATE SET ms=ms+excluded.ms",
           (user_id, today(), int(ms)))
