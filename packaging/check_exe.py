"""打包后自检：用打包好的程序（--sa-harness 模式）运行全部内置编程题的参考解，确认判题可用。

用法：python packaging/check_exe.py dist/StudyAgent.exe
"""
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from studyagent import grading  # noqa: E402

exe = os.path.abspath(sys.argv[1])
grading.python_cmd = lambda harness, src, cfile: [exe, "--sa-harness", harness, src, cfile]

questions = json.load(open(os.path.join(ROOT, "studyagent", "seed_data", "prog_questions.json"), encoding="utf-8"))
failed = []
for q in questions:
    cases = [e for e in q.get("examples", []) if not e.get("doubt") and isinstance(e.get("args"), list) and "expect" in e]
    cases += q.get("hidden") or []
    r = grading.run_code("python", q["ref"], cases, per_case=20.0)
    ok = "results" in r and all(x.get("pass") for x in r["results"])
    if not ok:
        failed.append((q.get("no"), q.get("title"), r.get("error") or [x for x in r["results"] if not x.get("pass")][:1]))
print("通过 %d / %d 道题" % (len(questions) - len(failed), len(questions)))
for f in failed:
    print("未通过:", f)
sys.exit(1 if failed else 0)
