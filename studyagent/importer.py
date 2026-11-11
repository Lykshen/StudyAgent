"""Import: file -> text -> model splits into questions of any type, assigns category + tier -> user reviews -> saved."""
import io
import json
import re
import secrets
import time
import zipfile

from . import agents, db, learning as L

TYPES = ("single", "multi", "judge", "fill", "short", "code")


def extract_text(filename, data):
    name = filename.lower()
    if name.endswith(".pdf"):
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(data)) as pdf:
                text = "\n".join((p.extract_text() or "") for p in pdf.pages)
        except Exception:
            from pypdf import PdfReader
            text = "\n".join((p.extract_text() or "") for p in PdfReader(io.BytesIO(data)).pages)
        if not text.strip():
            raise ValueError("这个 PDF 里读不出文字（可能是扫描图片）。请先转成文字再导入。")
        return text
    if name.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            xml = z.read("word/document.xml").decode("utf-8", "replace")
        xml = re.sub(r"</w:p>", "\n", xml)
        return re.sub(r"<[^>]+>", "", xml)
    if re.search(r"\.(txt|md|csv|json)$", name):
        for enc in ("utf-8", "gbk", "utf-16"):
            try:
                return data.decode(enc)
            except Exception:
                continue
    raise ValueError("暂不支持这种文件：请用 .txt / .md / .json / .csv / .pdf / .docx")


def chunk_text(t, size=5000):
    parts, cur = [], ""
    for para in re.split(r"\n(?=\s*(?:【|第\s*\d+\s*题|\d+[\.、．]\s*|[一二三四五六七八九十]+、|题目))", t):
        if len(cur) + len(para) > size and cur:
            parts.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + para
        while len(cur) > size:
            parts.append(cur[:size])
            cur = cur[size:]
    if cur.strip():
        parts.append(cur)
    return parts


def normalize(x, cat_names):
    """Validate one model-produced item. Returns dict with 'problems' listing what is missing."""
    t = x.get("type") if x.get("type") in TYPES else ("code" if x.get("examples") else "short")
    probs = []
    item = {"type": t, "title": str(x.get("title") or (x.get("stem") or "")[:30] or "未命名").strip()[:80],
            "stem": str(x.get("stem") or x.get("desc") or ""), "options": [], "answer": None, "analysis": str(x.get("analysis") or ""), "extra": {}}
    if not item["stem"]:
        probs.append("缺题面")
    if t in ("single", "multi"):
        item["options"] = [str(o) for o in (x.get("options") or [])]
        if len(item["options"]) < 2:
            probs.append("选项不足")
        try:
            a = x.get("answer")
            if t == "single":
                item["answer"] = _opt_index(a, item["options"])
            else:
                item["answer"] = sorted({_opt_index(v, item["options"]) for v in (a if isinstance(a, list) else [a])})
        except Exception:
            probs.append("答案无法识别")
    elif t == "judge":
        a = x.get("answer")
        item["answer"] = a if isinstance(a, bool) else str(a).strip().lower() in ("true", "对", "正确", "√", "1", "是", "t")
    elif t == "fill":
        a = x.get("answer")
        blanks = a if isinstance(a, list) else [a]
        item["answer"] = [b if isinstance(b, list) else [str(b)] for b in blanks if b is not None]
        item["extra"]["fill_rules"] = {"case_sensitive": bool(x.get("case_sensitive")), "ignore_spaces": True}
        item["extra"]["blanks"] = len(item["answer"])
        if not item["answer"]:
            probs.append("缺答案")
    elif t == "short":
        item["extra"]["rubric"] = str(x.get("rubric") or x.get("answer") or x.get("analysis") or "")
        item["answer"] = item["extra"]["rubric"]
        if not item["extra"]["rubric"]:
            probs.append("缺评分要点")
    elif t == "code":
        exs = []
        for e in x.get("examples") or []:
            args, exp = e.get("args"), e.get("expect")
            if not isinstance(args, list):
                try:
                    args = json.loads("[" + str(e.get("input", "")).replace("(", "[").replace(")", "]") + "]")
                except Exception:
                    args = None
            if exp is None and e.get("output") is not None:
                try:
                    exp = json.loads(str(e["output"]))
                except Exception:
                    exp = str(e["output"])
            ex = {"input": str(e.get("input") if e.get("input") is not None else (json.dumps(args, ensure_ascii=False)[1:-1] if isinstance(args, list) else "")),
                  "output": str(e.get("output") if e.get("output") is not None else json.dumps(exp, ensure_ascii=False)), "note": str(e.get("note") or "")}
            if isinstance(args, list) and exp is not None:
                ex["args"], ex["expect"] = args, exp
            exs.append(ex)
        item["extra"].update({"examples": exs, "hidden": [], "params": [str(p) for p in (x.get("params") or [])] or None})
        if not exs:
            probs.append("缺示例")
    cls = {"tier": 2, "score": 4, "points": [], "reason": ""}
    try:
        cls["tier"] = max(1, min(4, int(round(float(x.get("tier"))))))
        cls["score"] = max(1, min(10, int(float(x.get("score") or cls["tier"] * 2))))
    except Exception:
        probs.append("没有有效层级，已暂定 L2")
    cls["points"] = [str(p) for p in (x.get("points") or [])][:4]
    cls["reason"] = str(x.get("reason") or "")[:60]
    cat = x.get("category")
    cls["category_id"] = None
    cls["category_name"] = None
    if cat_names:
        if isinstance(cat, int) or (isinstance(cat, str) and cat.isdigit()):
            cls["category_id"] = int(cat) if int(cat) in cat_names else None
        if cls["category_id"] is None and cat:
            hit = [k for k, v in cat_names.items() if v == str(cat)]
            cls["category_id"] = hit[0] if hit else None
            if not hit:
                cls["category_name"] = str(cat)[:30]
    item["cls"] = cls
    item["problems"] = probs
    return item


def _opt_index(a, options):
    if isinstance(a, int):
        if 0 <= a < len(options):
            return a
        raise ValueError
    s = str(a).strip()
    if len(s) == 1 and s.upper() in "ABCDEFGH":
        i = "ABCDEFGH".index(s.upper())
        if i < len(options):
            return i
    if s.isdigit() and int(s) < len(options):
        return int(s)
    for i, o in enumerate(options):
        if s == o.strip() or re.sub(r"^[A-H][\.、．\s]*", "", o).strip() == s:
            return i
    raise ValueError


def parse(user_id, subject_id, text, on_progress=None, should_stop=lambda: False):
    cats = {c["id"]: c["name"] for c in db.q("SELECT id, name FROM categories WHERE subject_id=? AND lesson_only=0 ORDER BY sort", (subject_id,))}
    try:
        direct = json.loads(text)
    except Exception:
        direct = None
    if isinstance(direct, list) and direct and isinstance(direct[0], dict) and ("stem" in direct[0] or "type" in direct[0]):
        return [normalize(x, cats) for x in direct]
    guide = ("题型 type：single 单选、multi 多选、judge 判断、fill 填空、short 简答、code 编程（LeetCode 核心代码模式，函数名 solve）。\n"
             "分类 category：优先填下列已有分类的 id；都不合适就填一个新的分类名称（中文）：\n%s\n\n层级 tier：\n%s") % (
        "\n".join("%d %s" % (k, v) for k, v in cats.items()) or "（还没有分类）", agents.tier_guide())
    schema = ('[{"type":"single","title":"简短题名","stem":"完整题干","options":["选项文本"],"answer":"单选填选项序号(0起)；多选填序号数组；判断填true/false；填空填每空可接受答案的数组，如[[\\"答案\\",\\"同义答案\\"]]；简答填参考答案要点",'
              '"analysis":"解析","params":["编程题参数名"],"examples":[{"input":"按参数顺序逗号分隔的字面量","output":"期望输出","args":[参数JSON],"expect":期望输出JSON}],'
              '"category":12,"tier":2,"score":4,"points":["知识点"],"reason":"分层理由"}]')
    items = []
    parts = chunk_text(text)
    for i, part in enumerate(parts):
        if should_stop():
            break
        prompt = ("下面是一段学习资料或题目（可能有多道题，也可能夹杂无关文字）。请拆出其中每一道完整的题，保持原题意思，"
                  "原文没有答案的不要编造答案（answer 留空，analysis 写“原文无答案”）。\n%s\n\n只输出 JSON 数组，每道题格式：%s\n\n资料：\n%s") % (guide, schema, part)
        arr = agents.json_task(user_id, "import", prompt)
        items += [normalize(x, cats) for x in arr if isinstance(x, dict)]
        if on_progress:
            on_progress(i + 1, len(parts), items)
    return items


def save_questions(user_id, items, source="导入", private=True, subject_id=None, new_category_ok=True):
    g = L.ensure_goal(user_id)
    sid = subject_id or g["subject_id"]
    existing = {c["name"]: c["id"] for c in db.q("SELECT id, name FROM categories WHERE subject_id=?", (sid,))}
    ids = []
    now = time.time()
    for it in items:
        cls = it.get("cls") or {}
        cid = cls.get("category_id")
        if not cid and cls.get("category_name") and new_category_ok:
            nm = cls["category_name"]
            if nm not in existing:
                mx = (db.q1("SELECT MAX(sort) m FROM categories WHERE subject_id=?", (sid,)) or {}).get("m") or 0
                existing[nm] = db.run("INSERT INTO categories(subject_id, name, sort) VALUES (?,?,?)", (sid, nm, mx + 1))
            cid = existing[nm]
        qid = "u" + secrets.token_hex(5)
        db.run("""INSERT INTO questions(id, subject_id, category_id, type, title, stem, options, answer, analysis, extra, tier, score, points,
                  source, cls_by, cls_reason, verified, status, owner_id, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
               (qid, sid, cid, it["type"], it["title"], it["stem"], db.dumps(it.get("options") or []), db.dumps(it.get("answer")),
                it.get("analysis") or "", db.dumps(it.get("extra") or {}), int(cls.get("tier") or 2), int(cls.get("score") or 4),
                db.dumps(cls.get("points") or []), source, "user" if cls.get("edited") else "ai", cls.get("reason") or "", 0, "published",
                user_id if private else None, now, now))
        ids.append(qid)
    db.audit(user_id, "questions.import", source, {"count": len(ids)})
    return ids
