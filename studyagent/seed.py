"""Seed the first subject: programming 机考 (46 code questions w/ hidden tests, LeetCode Hot 100 links, 11 lessons)."""
import json
import os
import time

from . import db

HERE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seed_data")

TOPICS = [
    ("T1", "字符串与模拟", ["字符串处理", "输入解析与查找", "编程基础/区间", "位运算"], ["哈希", "技巧"]),
    ("T2", "排序与自定义比较", ["排序"], ["普通数组", "矩阵"]),
    ("T3", "双指针、滑动窗口、前缀和", ["双指针/查找", "滑动窗口", "前缀和"], ["双指针", "滑动窗口", "子串"]),
    ("T4", "栈、队列、单调栈、堆", ["栈与队列"], ["栈", "堆"]),
    ("T5", "链表", ["链表"], ["链表"]),
    ("T6", "数组遍历、递归、二分", ["数组与遍历"], ["二分查找"]),
    ("T7", "二叉树与哈希表", ["树与哈希表"], ["二叉树"]),
    ("T8", "DFS、BFS、回溯", ["搜索算法（DFS / BFS / 回溯）"], ["回溯"]),
    ("T9", "图、拓扑排序、并查集", ["图", "并查集"], ["图论"]),
    ("T10", "贪心与动态规划", ["贪心算法", "动态规划"], ["贪心算法", "动态规划", "多维动态规划"]),
]

PROG_EXAM = {
    "name": "编程机考", "duration": 150, "pass": 150, "excellent": 300,
    "sections": [
        {"name": "一星题", "count": 2, "types": ["code"], "tiers": [1, 2], "points": 100},
        {"name": "二星题", "count": 1, "types": ["code"], "tiers": [3, 4], "points": 200},
    ],
    "rules": "LeetCode 核心代码模式；每题按隐藏用例通过率给分；机考不出原题。",
}

GENERIC_EXAM = {
    "name": "综合测试", "duration": 60, "pass": 60, "excellent": 85,
    "sections": [
        {"name": "基础题", "count": 10, "types": ["single", "judge"], "tiers": [1, 2], "points": 4},
        {"name": "提高题", "count": 5, "types": ["multi", "fill"], "tiers": [2, 3], "points": 6},
        {"name": "综合题", "count": 2, "types": ["short", "code"], "tiers": [3, 4], "points": 15},
    ],
}


def seed_if_empty():
    if db.q1("SELECT 1 FROM subjects LIMIT 1"):
        return False
    now = time.time()
    sid = db.run("INSERT INTO subjects(owner_id, name, description, exam_profile, created_at) VALUES (NULL,?,?,?,?)",
                 ("编程机考", "华为风格编程机考：LeetCode 核心代码模式，3 题 150 分钟。",
                  db.dumps(PROG_EXAM), now))
    lessons = {l["key"]: l for l in json.load(open(os.path.join(HERE, "prog_lessons.json"), encoding="utf-8"))}
    cat_ids = {}
    intro = db.run("INSERT INTO categories(subject_id, name, sort, description, lesson_only) VALUES (?,?,?,?,1)",
                   (sid, "机考入门", 0, lessons["T0"]["intro"]))
    cat_ids["T0"] = intro
    for i, (key, name, _pdf, _hot) in enumerate(TOPICS, start=1):
        cat_ids[key] = db.run("INSERT INTO categories(subject_id, name, sort, description, keywords) VALUES (?,?,?,?,?)",
                              (sid, name, i, lessons[key]["intro"], name))
    for key, les in lessons.items():
        db.run("INSERT INTO lessons(category_id, content, status, generated_by, updated_at) VALUES (?,?,?,?,?)",
               (cat_ids[key], db.dumps(les), "published", "builtin", now))

    def topic_for(cat, is_hot):
        for key, _n, pdf, hot in TOPICS:
            if cat in (hot if is_hot else pdf):
                return cat_ids[key]
        return cat_ids["T1"]

    pdf = json.load(open(os.path.join(HERE, "prog_questions.json"), encoding="utf-8"))
    with db.tx() as c:
        for i, p in enumerate(pdf, start=1):
            tier = 1 if p["star"] == "一星" else 3 if p["star"] == "二星" else 2
            extra = {"params": p.get("params"), "examples": p["examples"], "hidden": p.get("hidden", []),
                     "ref": p.get("ref", ""), "level": p["star"], "orig_category": p["cat"], "pdf_src": p.get("src")}
            c.execute("""INSERT INTO questions(id, subject_id, category_id, type, title, stem, extra, tier, score, points, source,
                         source_ref, verified, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (f"p{i}", sid, topic_for(p["cat"], False), "code", p["title"], p["desc"], db.dumps(extra), tier,
                       tier * 2 + 1, db.dumps(p.get("tags", [])[:4]), "真题 PDF", p.get("src", ""), 1, "published", now, now))
        hot = json.load(open(os.path.join(HERE, "hot100.json"), encoding="utf-8"))
        for h in hot:
            tier = 1 if h["diff"] == "简单" else 2 if h["diff"] == "中等" else 4
            extra = {"url": f"https://leetcode.cn/problems/{h['slug']}/", "no": h["no"], "level": h["diff"], "orig_category": h["cat"]}
            c.execute("""INSERT INTO questions(id, subject_id, category_id, type, title, stem, extra, tier, score, points, source,
                         verified, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (h["id"], sid, topic_for(h["cat"], True), "external", f"{h['no']}. {h['title']}",
                       "这道题在力扣上作答。做完回来标记完成；没把握就标「需复习」。", db.dumps(extra), tier, tier * 2 + 1,
                       db.dumps([h["cat"]]), "力扣热题 100", 1, "published", now, now))
    db.run("INSERT OR REPLACE INTO meta(k, v) VALUES ('generic_exam', ?)", (db.dumps(GENERIC_EXAM),))
    return True
