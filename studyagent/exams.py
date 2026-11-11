"""Tests: rules from the subject's exam profile, paper generation with gap checks, snapshot, timed attempt, idempotent submit."""
import random
import time

from . import db, grading, learning as L


def profile_for(subject_id):
    s = db.q1("SELECT exam_profile FROM subjects WHERE id=?", (subject_id,))
    p = db.J(s["exam_profile"], {}) if s else {}
    if not p.get("sections"):
        p = db.J((db.q1("SELECT v FROM meta WHERE k='generic_exam'") or {}).get("v"), {})
    return p


def _learned_categories(user_id, plan):
    t = L.today()
    cats = set()
    for d in plan["days"]:
        if d["date"] <= t:
            for x in d["tasks"]:
                if x["type"] == "learn":
                    cats.add(x["category_id"])
    for r in db.q("SELECT category_id FROM user_lessons WHERE user_id=? AND done_at IS NOT NULL", (user_id,)):
        cats.add(r["category_id"])
    prog = L.all_progress(user_id)
    for q in L.visible_questions(user_id, plan["goal"]["subject_id"]):
        if prog.get(q["id"], {}).get("status", "todo") != "todo":
            cats.add(q["category_id"])
    return cats


def gradable(q):
    if q["type"] == "external":
        return False
    if q["type"] == "code":
        return bool(grading.code_cases(q, include_hidden=False))
    if q["type"] in ("single", "multi", "judge", "fill"):
        return q["answer"] is not None
    return q["type"] == "short"


def generate(user_id, scope="learned", allow_recent=False, seed=None):
    g = L.ensure_goal(user_id)
    plan = L.build_plan(user_id, g)
    prof = profile_for(g["subject_id"])
    rnd = random.Random(seed)
    learned = _learned_categories(user_id, plan)
    recent = set()
    for e in db.q("SELECT paper, created_at FROM exams WHERE user_id=?", (user_id,)):
        if time.time() - (e["created_at"] or 0) < 86400 * int(g["recent_window"] or 14):
            recent |= {it["qid"] for it in db.J(e["paper"], {}).get("items", []) if it.get("qid")}
    open_reviews = {r["question_id"] for r in L.reviews(user_id)}
    prog = L.all_progress(user_id)
    pool = [q for q in L.visible_questions(user_id, g["subject_id"]) if gradable(q)]
    if scope == "learned":
        pool = [q for q in pool if q["category_id"] in learned]
    elif scope == "weak":
        pool = [q for q in pool if q["id"] in open_reviews or prog.get(q["id"], {}).get("tags")]
    if not allow_recent:
        pool = [q for q in pool if q["id"] not in recent]
    items, gaps, used = [], [], set()
    for sec in prof["sections"]:
        cand = [q for q in pool if q["type"] in sec["types"] and q["tier"] in sec["tiers"] and q["id"] not in used]
        if len(cand) < sec["count"]:
            gaps.append({"section": sec["name"], "need": sec["count"], "have": len(cand), "types": [L.TYPE_NAMES.get(t, t) for t in sec["types"]],
                         "tiers": ["L%d" % t for t in sec["tiers"]]})
            continue
        cand.sort(key=lambda q: (-(q["id"] in open_reviews) * 5 - (prog.get(q["id"], {}).get("status", "todo") == "todo") * 2 + rnd.random() * 4))
        for q in cand[:sec["count"]]:
            used.add(q["id"])
            items.append({"qid": q["id"], "section": sec["name"], "points": sec["points"], "type": q["type"], "version": q["version"],
                          "title": q["title"], "stem": q["stem"], "options": q["options"], "answer": q["answer"], "extra": q["extra"],
                          "analysis": q["analysis"], "tier": q["tier"], "category_id": q["category_id"]})
    if gaps:
        return {"gaps": gaps, "excluded_recent": len(recent) if not allow_recent else 0}
    return {"items": items, "profile": prof}


def create(user_id, etype, scope, allow_recent, sched_date=None, minutes=None, items=None, source="bank"):
    g = L.ensure_goal(user_id)
    if items is None:
        r = generate(user_id, scope, allow_recent)
        if r.get("gaps"):
            return r
        items, prof = r["items"], r["profile"]
    else:
        prof = profile_for(g["subject_id"])
    paper = {"items": items, "duration": int(minutes or prof.get("duration", 60)), "pass": prof.get("pass"), "excellent": prof.get("excellent"),
             "total": sum(i["points"] for i in items), "scope": scope, "source": source, "name": prof.get("name", "测试")}
    if sched_date:
        ex = db.q1("SELECT id FROM exams WHERE user_id=? AND goal_id=? AND sched_date=?", (user_id, g["id"], sched_date))
        if ex:
            return {"id": ex["id"]}
    eid = db.run("""INSERT INTO exams(user_id, goal_id, type, sched_date, status, paper, created_at) VALUES (?,?,?,?,?,?,?)""",
                 (user_id, g["id"], etype, sched_date, "ready", db.dumps(paper), time.time()))
    return {"id": eid}


def public_paper(paper, reveal=False):
    out = dict(paper)
    items = []
    for it in paper["items"]:
        x = {k: it.get(k) for k in ("qid", "section", "points", "type", "title", "stem", "options", "tier")}
        ex = it.get("extra") or {}
        x["extra"] = {k: ex.get(k) for k in ("params", "fill_rules", "blanks") if k in ex}
        if it["type"] == "code":
            x["extra"]["examples"] = [{"input": e.get("input"), "output": e.get("output")} for e in ex.get("examples") or [] if not e.get("doubt")]
        if reveal:
            x["answer"], x["analysis"] = it.get("answer"), it.get("analysis")
        items.append(x)
    out["items"] = items
    return out


def get(user_id, eid):
    e = db.q1("SELECT * FROM exams WHERE id=? AND user_id=?", (eid, user_id))
    if not e:
        return None
    e["paper"] = db.J(e["paper"], {})
    e["answers"] = db.J(e["answers"], {})
    e["flags"] = db.J(e["flags"], {})
    e["result"] = db.J(e["result"], None)
    e["adjustments"] = db.J(e["adjustments"], [])
    if e["status"] == "running" and e["deadline_at"] and time.time() > e["deadline_at"]:
        finish(user_id, e, auto=True)
        return get(user_id, eid)
    return e


def start(user_id, eid):
    e = get(user_id, eid)
    if not e:
        return None
    if e["status"] == "ready":
        now = time.time()
        db.run("UPDATE exams SET status='running', start_at=?, deadline_at=? WHERE id=?", (now, now + e["paper"]["duration"] * 60, eid))
    return get(user_id, eid)


def save_answers(user_id, eid, answers, flags=None):
    e = get(user_id, eid)
    if not e or e["status"] != "running":
        return {"error": "测试不在进行中（可能已交卷或已到时间）"}
    merged = {**e["answers"], **(answers or {})}
    db.run("UPDATE exams SET answers=?, flags=? WHERE id=?", (db.dumps(merged), db.dumps({**e["flags"], **(flags or {})}), eid))
    return {"saved_at": time.time()}


def _grade_item(user_id, it, ans, lang):
    q = {"type": it["type"], "answer": it.get("answer"), "extra": it.get("extra") or {}, "stem": it.get("stem"), "title": it.get("title"), "analysis": it.get("analysis")}
    pts = it["points"]
    if ans in (None, "", [], {}):
        return {"score": 0, "max": pts, "kind": "未作答"}
    if it["type"] == "code":
        code = ans.get("code") if isinstance(ans, dict) else ans
        lg = ans.get("lang", lang) if isinstance(ans, dict) else lang
        cases = grading.code_cases(q)
        r = grading.run_code(lg, code or "", cases)
        if r.get("error"):
            return {"score": 0, "max": pts, "kind": r["error"][:80]}
        n = sum(1 for x in r["results"] if x["pass"])
        return {"score": round(pts * n / max(1, len(cases)), 1), "max": pts, "passed": n, "total": len(cases),
                "kind": "全部通过" if n == len(cases) else grading.kind_summary(r["results"])}
    if it["type"] == "short":
        from . import agents
        try:
            g = agents.grade_short(user_id, q, ans)
            return {"score": round(pts * g["ratio"], 1), "max": pts, "kind": "AI 辅助评分", "ai": True, "reason": g["reason"]}
        except Exception as ex:
            return {"score": 0, "max": pts, "kind": "待评分（%s）" % str(ex)[:40], "pending": True}
    ratio, detail = grading.grade_objective(q, ans)
    return {"score": round(pts * ratio, 1), "max": pts, "kind": "正确" if ratio == 1 else ("部分正确" if ratio > 0 else "错误"), "detail": detail}


def finish(user_id, e, auto=False):
    # idempotent: only the first transition running/ready -> grading wins
    c = db.connect()
    cur = c.execute("UPDATE exams SET status='grading', submitted_at=? WHERE id=? AND status IN ('running','ready')", (time.time(), e["id"]))
    c.commit()
    if cur.rowcount == 0:
        return get(user_id, e["id"])
    g = db.q1("SELECT lang FROM goals WHERE id=?", (e["goal_id"],)) or {"lang": "python"}
    items = []
    for it in e["paper"]["items"]:
        ans = e["answers"].get(it["qid"])
        r = _grade_item(user_id, it, ans, g["lang"])
        r["qid"] = it["qid"]
        items.append(r)
        if it.get("qid"):
            full = r["score"] >= r["max"]
            db.run("""INSERT INTO attempts(user_id, question_id, version, mode, answer, score, max_score, detail, independent, used_hint, viewed_answer, created_at, day)
                      VALUES (?,?,?,?,?,?,?,?,1,0,0,?,date('now','localtime'))""",
                   (user_id, it["qid"], it.get("version"), "exam", db.dumps(ans), r["score"], r["max"], db.dumps(r), time.time()))
            if not r.get("pending"):
                if full:
                    p = L.progress(user_id, it["qid"])
                    if p["status"] != "done":
                        L.save_progress(user_id, it["qid"], status="done")
                    L.review_result(user_id, it["qid"], True)
                else:
                    rv = db.q1("SELECT done FROM reviews WHERE user_id=? AND question_id=?", (user_id, it["qid"]))
                    if not rv or rv["done"]:
                        L.add_review(user_id, it["qid"])
                    else:
                        L.review_result(user_id, it["qid"], False)
    total = round(sum(i["score"] for i in items), 1)
    by_cat = {}
    for it, r in zip(e["paper"]["items"], items):
        c2 = by_cat.setdefault(it.get("category_id"), {"score": 0, "max": 0})
        c2["score"] += r["score"]
        c2["max"] += r["max"]
    used = round(((e.get("submitted_at") or time.time()) - (e["start_at"] or time.time())) / 60)
    result = {"items": items, "total": total, "max": e["paper"]["total"], "auto": auto, "pending": any(i.get("pending") for i in items),
              "by_category": [{"category_id": k, **v} for k, v in by_cat.items()], "used_min": min(e["paper"]["duration"], max(0, used))}
    db.run("UPDATE exams SET status='done', result=? WHERE id=?", (db.dumps(result), e["id"]))
    return get(user_id, e["id"])


def adjust(user_id, eid, qid, new_score, reason):
    e = get(user_id, eid)
    if not e or e["status"] != "done":
        return {"error": "只能复核已交卷的测试"}
    res = e["result"]
    for it in res["items"]:
        if it["qid"] == qid:
            old = it["score"]
            it["score"] = max(0, min(it["max"], float(new_score)))
            it["adjusted"] = True
            res["total"] = round(sum(i["score"] for i in res["items"]), 1)
            adj = e["adjustments"] + [{"qid": qid, "old": old, "new": it["score"], "reason": reason, "by": user_id, "at": time.time()}]
            db.run("UPDATE exams SET result=?, adjustments=? WHERE id=?", (db.dumps(res), db.dumps(adj), eid))
            db.audit(user_id, "exam.adjust", str(eid), {"qid": qid, "old": old, "new": it["score"], "reason": reason})
            return get(user_id, eid)
    return {"error": "这张试卷里没有这道题"}
