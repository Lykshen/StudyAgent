"""Help other devices reach this computer: Windows firewall rule for StudyAgent.

Windows blocks inbound connections on "Public" networks, and if the first-run firewall prompt was
cancelled it even adds an explicit block rule for the program (block rules beat allow rules).
allow_windows_firewall() removes StudyAgent's own block rules and adds allow rules, asking for
administrator permission through the normal Windows UAC prompt.
"""
import os
import subprocess
import sys
import tempfile
import time


def frozen():
    return bool(getattr(sys, "frozen", False))


def allow_windows_firewall(port):
    """Returns {"ok": bool, "message": str}."""
    if os.name != "nt":
        return {"ok": False, "message": "只有 Windows 需要这一步。macOS 如果弹出「允许传入连接」，选允许即可。"}
    port = int(port)
    exe = sys.executable
    tmp = tempfile.mkdtemp(prefix="sa_fw_")
    marker = os.path.join(tmp, "done.txt")
    lines = ["@echo off", "chcp 65001 >nul"]
    if frozen():
        # Only touch rules for our own exe (never for a shared python.exe).
        lines += ['netsh advfirewall firewall delete rule name=all dir=in program="%s" >nul 2>&1' % exe,
                  'netsh advfirewall firewall add rule name="StudyAgent" dir=in action=allow program="%s" enable=yes profile=any >nul' % exe]
    lines += ['netsh advfirewall firewall delete rule name="StudyAgent 端口 %d" >nul 2>&1' % port,
              'netsh advfirewall firewall add rule name="StudyAgent 端口 %d" dir=in action=allow protocol=TCP localport=%d enable=yes profile=any >nul' % (port, port),
              'if %%errorlevel%%==0 echo ok> "%s"' % marker]
    script = os.path.join(tmp, "allow.cmd")
    with open(script, "w", encoding="utf-8") as f:
        f.write("\r\n".join(lines) + "\r\n")
    env = dict(os.environ, SA_FW=script)
    ps = "try { Start-Process -FilePath $env:SA_FW -Verb RunAs -WindowStyle Hidden -Wait -ErrorAction Stop } catch { exit 5 }"
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                           env=env, capture_output=True, timeout=120, creationflags=0x08000000)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": "没能启动设置程序：%s" % e}
    for _ in range(10):
        if os.path.exists(marker):
            return {"ok": True, "message": "已允许 StudyAgent 通过 Windows 防火墙（端口 %d）。" % port}
        time.sleep(0.3)
    if r.returncode == 5:
        return {"ok": False, "message": "没有获得管理员允许。请再点一次，并在 Windows 弹出的窗口里点「是」。"}
    return {"ok": False, "message": "防火墙规则没有加上。可以手动设置：Windows 安全中心 → 防火墙和网络保护 → 允许应用通过防火墙 → 勾选 StudyAgent 的「专用」和「公用」。"}
