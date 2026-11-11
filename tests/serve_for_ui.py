import os, sys, shutil, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
D = os.path.join(tempfile.gettempdir(), "sa_ui"); os.environ["STUDYAGENT_DATA"] = D; shutil.rmtree(D, ignore_errors=True)
import mock_llm
mock_llm.serve(9912)
from studyagent import create_app
app = create_app()
app.run(host="127.0.0.1", port=8799, threaded=True)
