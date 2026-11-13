"""StudyAgent desktop app: runs the platform in the background and shows it in its own window (no browser).

Packaged into StudyAgent.exe by build_windows.bat. Data lives in a per-user folder so it survives updates:
  Windows  %APPDATA%\\StudyAgent        macOS ~/Library/Application Support/StudyAgent        Linux ~/.local/share/StudyAgent
"""
import os
import socket
import sys
import threading
import time


def data_dir():
    if os.environ.get("STUDYAGENT_DATA"):
        return os.environ["STUDYAGENT_DATA"]
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "StudyAgent")


def free_port(preferred):
    for port in [preferred] + list(range(preferred + 1, preferred + 50)):
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            s.close()
    return preferred


def serve(app, host, port):
    from werkzeug.serving import make_server
    srv = make_server(host, port, app, threaded=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def wait_up(port, timeout=20):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            return True
        except OSError:
            time.sleep(0.1)
    return False


def main():
    # The packaged exe re-launches itself to run students' Python code in a separate process.
    if len(sys.argv) > 1 and sys.argv[1] == "--sa-harness":
        from studyagent.grading import run_harness_inline
        run_harness_inline(sys.argv[2:])
        return
    os.environ.setdefault("STUDYAGENT_DATA", data_dir())
    os.environ["SA_DESKTOP"] = "1"
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from studyagent import config, create_app
    cfg = config.load()
    if "--lan" in sys.argv and not cfg.get("lan"):
        config.save(lan=True)
    # Always listen on the network; requests from other devices are refused while
    # 「允许手机连接」 is off, so switching it on works immediately without a restart.
    host = "0.0.0.0"
    os.environ["SA_BIND_ALL"] = "1"
    port = free_port(int(cfg.get("port") or 8765))
    app = create_app()
    srv = serve(app, host, port)
    wait_up(port)
    url = "http://127.0.0.1:%d/" % port
    try:
        import webview  # pywebview: native window (Edge WebView2 on Windows, WebKit on macOS)
    except ImportError:
        webview = None
    if webview is None or "--browser" in sys.argv:
        import webbrowser
        print("StudyAgent 正在运行：%s（关闭这个窗口即退出）" % url)
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        webview.create_window("StudyAgent 学习刷题", url, width=1360, height=880, min_size=(900, 600), text_select=True)
        webview.start(private_mode=False)  # keep localStorage (login token) between launches
    srv.shutdown()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()
