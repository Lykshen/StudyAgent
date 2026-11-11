"""Grading for every question type. Code runs locally in a child process with per-case time limits.
Note: the code runner isolates crashes and endless loops, but it is not a security sandbox for untrusted users."""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

PY_HARNESS = r'''
import io, json, sys, time, traceback
real = sys.__stdout__
src = open(sys.argv[1], encoding="utf-8").read()
cases = json.load(open(sys.argv[2], encoding="utf-8"))
sys.stdout = io.StringIO()
ns = {"__name__": "solution"}
# Same convenience imports as LeetCode's Python core-code mode, so solutions can use Counter, heapq, List... directly
exec("from typing import *\nfrom collections import *\nfrom heapq import *\nfrom bisect import *\nfrom itertools import *\nfrom functools import *\nfrom math import inf, gcd, comb, isqrt, sqrt, ceil, floor, log2\nimport collections, heapq, bisect, itertools, functools, math, re, string, operator, random", ns)
try:
    exec(compile(src, "solution.py", "exec"), ns)
    fn = ns.get("solve")
    if fn is None and "Solution" in ns:
        o = ns["Solution"]()
        ms = [m for m in dir(o) if not m.startswith("_") and callable(getattr(o, m))]
        fn = getattr(o, ms[0]) if ms else None
    if fn is None:
        raise Exception("没找到函数：请定义 def solve(...) 或 class Solution")
except Exception:
    real.write(json.dumps({"error": "编译/运行错误：" + traceback.format_exc(limit=2).strip().splitlines()[-1]}, ensure_ascii=False) + "\n"); real.flush(); sys.exit(0)
real.write(json.dumps({"ready": True}) + "\n"); real.flush()
for i, a in enumerate(cases):
    t = time.time()
    try:
        r = fn(*a)
        out = {"i": i, "got": json.dumps(r, ensure_ascii=False, default=list), "ms": (time.time() - t) * 1000}
    except Exception:
        out = {"i": i, "err": traceback.format_exc(limit=2).strip().splitlines()[-1], "ms": (time.time() - t) * 1000}
    real.write(json.dumps(out, ensure_ascii=False) + "\n"); real.flush()
'''

JS_HARNESS = r'''
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");
console.log = () => {};
let fn;
try {
  fn = new Function(src + "\n;return (typeof solve!=='undefined')?solve:(typeof Solution!=='undefined'?(...a)=>{const o=new Solution();const m=Object.getOwnPropertyNames(Solution.prototype).find(k=>k!=='constructor');return o[m](...a);}:null);")();
  if (!fn) throw new Error("没找到函数：请定义 function solve(...)");
} catch (e) { out({error: "编译/运行错误：" + e.message}); process.exit(0); }
out({ready: true});
cases.forEach((a, i) => { const t = Date.now();
  try { const v = fn(...a); out({i, got: JSON.stringify(v === undefined ? null : v), ms: Date.now() - t}); }
  catch (e) { out({i, err: String(e && e.message || e), ms: Date.now() - t}); } });
'''

KIND_TXT = {"AC": "通过", "WA": "答案错误", "RE": "运行错误", "TLE": "超时", "SKIP": "未运行（前一用例超时）"}


def python_cmd(harness, src, cfile):
    """Command that runs the Python harness. In the packaged exe there is no separate python.exe,
    so the exe re-launches itself with --sa-harness (see desktop.py)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, "--sa-harness", harness, src, cfile]
    if os.environ.get("STUDYAGENT_SELF_HARNESS"):  # used by tests to exercise the packaged path
        return [sys.executable, os.environ["STUDYAGENT_SELF_HARNESS"], "--sa-harness", harness, src, cfile]
    return [sys.executable, "-I", harness, src, cfile]


def run_harness_inline(argv):
    """Entry used by the packaged app: argv = [harness_path, src, cases]."""
    sys.argv = [argv[0]] + argv[1:]
    if sys.__stdout__ is None:  # windowed exe has no console streams; fd 1 is the pipe from the parent
        try:
            sys.stdout = sys.__stdout__ = os.fdopen(1, "w", encoding="utf-8", buffering=1)
        except OSError:
            pass
    code = open(argv[0], encoding="utf-8").read()
    exec(compile(code, argv[0], "exec"), {"__name__": "__main__"})


def languages():
    langs = {"python": True}
    langs["javascript"] = bool(shutil.which("node"))
    return langs


def _norm(v):
    if isinstance(v, str):
        t = v.strip()
        try:
            return json.dumps(json.loads(t), sort_keys=True, ensure_ascii=False)
        except Exception:
            return json.dumps(t, ensure_ascii=False)
    return json.dumps(v, sort_keys=True, ensure_ascii=False)


def _limits():
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (1024 * 1024 * 1024, 1024 * 1024 * 1024))
    except Exception:
        pass


def run_code(lang, code, cases, per_case=5.0):
    """cases: [{"args": [...], "expect": ...}] -> {"error": str} | {"results": [...]}"""
    if lang not in ("python", "javascript"):
        return {"error": "%s 暂时不能在本机运行判题，可以用 AI 检查代码" % lang}
    if lang == "javascript" and not shutil.which("node"):
        return {"error": "本机没有安装 Node.js，无法运行 JavaScript。安装 Node.js 或改用 Python。"}
    tmp = tempfile.mkdtemp(prefix="sa_run_")
    try:
        src = os.path.join(tmp, "solution.py" if lang == "python" else "solution.js")
        harness = os.path.join(tmp, "harness.py" if lang == "python" else "harness.js")
        cfile = os.path.join(tmp, "cases.json")
        open(src, "w", encoding="utf-8").write(code)
        open(harness, "w", encoding="utf-8").write(PY_HARNESS if lang == "python" else JS_HARNESS)
        json.dump([c["args"] for c in cases], open(cfile, "w", encoding="utf-8"), ensure_ascii=False)
        cmd = python_cmd(harness, src, cfile) if lang == "python" else ["node", harness, src, cfile]
        kw = dict(stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, cwd=tmp)
        if os.name == "posix":
            kw["preexec_fn"] = _limits
        elif sys.platform.startswith("win"):
            kw["creationflags"] = 0x08000000  # CREATE_NO_WINDOW: no console flashes when judging
        p = subprocess.Popen(cmd, **kw)
        lines, lock = [], threading.Condition()

        def reader():
            for raw in p.stdout:
                with lock:
                    lines.append(raw.decode("utf-8", "replace"))
                    lock.notify_all()
            with lock:
                lines.append(None)
                lock.notify_all()

        threading.Thread(target=reader, daemon=True).start()
        results = [None] * len(cases)
        idx, ready, started = 0, False, time.time()
        deadline = time.time() + 20  # compile / startup budget
        while True:
            with lock:
                while idx >= len(lines) and time.time() < deadline:
                    lock.wait(timeout=max(0.01, deadline - time.time()))
                if idx >= len(lines):
                    break  # timeout
                line = lines[idx]
                idx += 1
            if line is None:
                break
            try:
                o = json.loads(line)
            except Exception:
                continue
            if "error" in o:
                p.kill()
                return {"error": o["error"]}
            if o.get("ready"):
                ready = True
                deadline = time.time() + per_case
                continue
            i = o.get("i")
            if i is None or i >= len(cases):
                continue
            c = cases[i]
            if "err" in o:
                results[i] = {"pass": False, "kind": "RE", "err": o["err"], "ms": o.get("ms")}
            else:
                try:
                    got = json.loads(o["got"])
                except Exception:
                    got = o["got"]
                ok = _norm(got) == _norm(c.get("expect"))
                results[i] = {"pass": ok, "kind": "AC" if ok else "WA", "got": o["got"], "ms": o.get("ms")}
            deadline = time.time() + per_case
        if p.poll() is None:
            p.kill()
        if not ready and all(r is None for r in results):
            return {"error": "程序启动超时或异常退出（可能占用内存过大）"}
        hit = False
        for i, r in enumerate(results):
            if r is None:
                results[i] = {"pass": False, "kind": "SKIP" if hit else "TLE"}
                hit = True
        return {"results": results}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def kind_summary(results):
    c = {}
    for r in results:
        if r["kind"] != "AC":
            c[r["kind"]] = c.get(r["kind"], 0) + 1
    return "，".join("%s %d" % (KIND_TXT[k], v) for k, v in c.items())


def code_cases(q, include_hidden=True):
    ex = q["extra"].get("examples") or []
    cases = [e for e in ex if not e.get("doubt") and isinstance(e.get("args"), list) and "expect" in e]
    return cases + (q["extra"].get("hidden") or [] if include_hidden else [])


def _norm_text(s, rules):
    s = str(s if s is not None else "")
    if rules.get("ignore_spaces", True):
        s = "".join(s.split())
    if not rules.get("case_sensitive", False):
        s = s.lower()
    return s


def grade_objective(q, answer):
    """Returns (ratio 0..1, detail). Raises ValueError for unsupported types."""
    t = q["type"]
    ans = q["answer"]
    if t == "single":
        ok = answer is not None and int(answer) == int(ans)
        return (1.0 if ok else 0.0), {"correct": ans}
    if t == "multi":
        ok = sorted(int(x) for x in (answer or [])) == sorted(int(x) for x in (ans or []))
        return (1.0 if ok else 0.0), {"correct": ans, "rule": "多选题全对得分，漏选或错选不得分"}
    if t == "judge":
        ok = answer is not None and bool(answer) == bool(ans)
        return (1.0 if ok else 0.0), {"correct": ans}
    if t == "fill":
        rules = q["extra"].get("fill_rules") or {}
        blanks = ans or []
        given = answer or []
        per = []
        for i, accepted in enumerate(blanks):
            acc = accepted if isinstance(accepted, list) else [accepted]
            g = given[i] if i < len(given) else ""
            per.append(any(_norm_text(g, rules) == _norm_text(a, rules) for a in acc))
        ratio = (sum(per) / len(per)) if per else 0.0
        return ratio, {"correct": blanks, "blanks": per, "rule": "按空计分；%s、%s" % (
            "区分大小写" if rules.get("case_sensitive") else "不区分大小写", "忽略空格" if rules.get("ignore_spaces", True) else "空格要一致")}
    raise ValueError("unsupported")
