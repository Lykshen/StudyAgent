# PyInstaller spec: python -m PyInstaller packaging/StudyAgent.spec
import os, sys
root = os.path.abspath(os.path.join(SPECPATH, ".."))
# stdlib modules students commonly import in their solutions must be bundled explicitly
student_libs = ["collections", "heapq", "itertools", "functools", "bisect", "math", "re", "string", "random", "statistics",
                "operator", "copy", "typing", "dataclasses", "fractions", "decimal", "array", "json", "io", "traceback", "time"]
a = Analysis([os.path.join(root, "desktop.py")], pathex=[root],
             datas=[(os.path.join(root, "studyagent", "web"), "studyagent/web"),
                    (os.path.join(root, "studyagent", "seed_data"), "studyagent/seed_data")],
             hiddenimports=student_libs + ["webview", "pdfplumber", "pypdf"],
             excludes=["tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], name="StudyAgent", console=False, upx=False,
          icon=os.path.join(root, "packaging", "icon.ico" if sys.platform.startswith("win") else "icon.png"))
if sys.platform == "darwin":
    app = BUNDLE(exe, name="StudyAgent.app", icon=os.path.join(root, "packaging", "icon.png"), bundle_identifier="com.studyagent.desktop")
