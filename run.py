"""Start the platform:  python run.py            (only this computer)
                         python run.py --lan      (phones / other computers on the same network can connect)"""
import argparse
import os
import sys
import threading
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description="StudyAgent 学习刷题 Agent 平台")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--lan", action="store_true", help="允许同一局域网的其它设备访问")
    ap.add_argument("--host", default=None)
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--data", default=None, help="数据目录（默认 ./data）")
    a = ap.parse_args()
    if a.data:
        os.environ["STUDYAGENT_DATA"] = os.path.abspath(a.data)
    from studyagent import config
    host = a.host or ("0.0.0.0" if (a.lan or config.load().get("lan")) else "127.0.0.1")
    os.environ["SA_LAN"] = "1" if host != "127.0.0.1" else "0"
    from studyagent import create_app, api, db
    app = create_app()
    url = "http://127.0.0.1:%d" % a.port
    print("\n  StudyAgent 已启动： %s" % url)
    if host != "127.0.0.1":
        for u in api.lan_addresses(a.port):
            print("  同一网络的其它设备： %s" % u)
        print("  其它设备首次打开时需要输入访问码，在「设置 → 设备与互通」里查看。")
    print("  数据目录： %s\n  按 Ctrl+C 停止。\n" % db.DATA_DIR)
    if not a.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host=host, port=a.port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
