"""SQLite storage. Schema is multi-user from day one; local mode simply has one user."""
import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager

DATA_DIR = os.environ.get("STUDYAGENT_DATA", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
DB_PATH = os.path.join(DATA_DIR, "studyagent.db")
_local = threading.local()

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, token TEXT UNIQUE NOT NULL,
  role TEXT NOT NULL DEFAULT 'user', tz TEXT DEFAULT 'Asia/Shanghai', prefs TEXT DEFAULT '{}', created_at REAL);
CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT NOT NULL, description TEXT DEFAULT '',
  exam_profile TEXT DEFAULT '{}', created_at REAL);
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY AUTOINCREMENT, subject_id INTEGER NOT NULL, parent_id INTEGER, name TEXT NOT NULL,
  sort INTEGER DEFAULT 0, description TEXT DEFAULT '', keywords TEXT DEFAULT '', lesson_only INTEGER DEFAULT 0, enabled INTEGER DEFAULT 1);
CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY, subject_id INTEGER NOT NULL, category_id INTEGER, type TEXT NOT NULL,
  title TEXT NOT NULL, stem TEXT DEFAULT '', options TEXT DEFAULT '[]', answer TEXT DEFAULT 'null', analysis TEXT DEFAULT '',
  extra TEXT DEFAULT '{}', tier INTEGER DEFAULT 2, score INTEGER DEFAULT 5, points TEXT DEFAULT '[]',
  source TEXT DEFAULT '', source_ref TEXT DEFAULT '', cls_by TEXT DEFAULT 'default', cls_reason TEXT DEFAULT '',
  verified INTEGER DEFAULT 0, status TEXT DEFAULT 'published', owner_id INTEGER, version INTEGER DEFAULT 1,
  created_at REAL, updated_at REAL);
CREATE INDEX IF NOT EXISTS q_cat ON questions(category_id);
CREATE TABLE IF NOT EXISTS question_versions (question_id TEXT, version INTEGER, snapshot TEXT, created_at REAL, PRIMARY KEY(question_id, version));
CREATE TABLE IF NOT EXISTS lessons (
  category_id INTEGER PRIMARY KEY, content TEXT NOT NULL, status TEXT DEFAULT 'published', generated_by TEXT DEFAULT 'builtin', updated_at REAL);
CREATE TABLE IF NOT EXISTS user_lessons (user_id INTEGER, category_id INTEGER, state TEXT DEFAULT '{}', done_at TEXT, PRIMARY KEY(user_id, category_id));
CREATE TABLE IF NOT EXISTS progress (
  user_id INTEGER, question_id TEXT, status TEXT DEFAULT 'todo', note TEXT DEFAULT '', tags TEXT DEFAULT '[]',
  time_ms INTEGER DEFAULT 0, assist TEXT DEFAULT '{}', code TEXT DEFAULT '{}', done_at TEXT, favorite INTEGER DEFAULT 0,
  PRIMARY KEY(user_id, question_id));
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, question_id TEXT, version INTEGER, mode TEXT,
  answer TEXT, score REAL, max_score REAL, detail TEXT, independent INTEGER, used_hint INTEGER, viewed_answer INTEGER,
  idem TEXT UNIQUE, created_at REAL, day TEXT);
CREATE TABLE IF NOT EXISTS reviews (
  user_id INTEGER, question_id TEXT, stage INTEGER DEFAULT 0, due TEXT, done INTEGER DEFAULT 0, history TEXT DEFAULT '[]', added TEXT,
  PRIMARY KEY(user_id, question_id));
CREATE TABLE IF NOT EXISTS goals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, subject_id INTEGER, name TEXT, start_date TEXT, exam_date TEXT,
  hours REAL DEFAULT 1.5, weekly_day INTEGER DEFAULT 0, monthly_day INTEGER DEFAULT 31, overflow TEXT, include_hard INTEGER DEFAULT 0,
  intervals TEXT DEFAULT '[1,3,7,14]', recent_window INTEGER DEFAULT 14, lang TEXT DEFAULT 'python', status TEXT DEFAULT 'active', current INTEGER DEFAULT 1, created_at REAL);
CREATE TABLE IF NOT EXISTS skipped (user_id INTEGER, question_id TEXT, at TEXT, PRIMARY KEY(user_id, question_id));
CREATE TABLE IF NOT EXISTS exams (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, goal_id INTEGER, type TEXT, sched_date TEXT, status TEXT,
  paper TEXT, answers TEXT DEFAULT '{}', flags TEXT DEFAULT '{}', start_at REAL, deadline_at REAL, submitted_at REAL,
  result TEXT, adjustments TEXT DEFAULT '[]', created_at REAL);
CREATE UNIQUE INDEX IF NOT EXISTS exam_sched ON exams(user_id, goal_id, sched_date) WHERE sched_date IS NOT NULL;
CREATE TABLE IF NOT EXISTS exam_skips (user_id INTEGER, goal_id INTEGER, date TEXT, PRIMARY KEY(user_id, goal_id, date));
CREATE TABLE IF NOT EXISTS study_log (user_id INTEGER, day TEXT, ms INTEGER DEFAULT 0, PRIMARY KEY(user_id, day));
CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, agent TEXT, title TEXT, goal_id INTEGER, created_at REAL, updated_at REAL);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT, conv_id INTEGER, role TEXT, content TEXT, model TEXT, tool_calls TEXT, tool_call_id TEXT, status TEXT DEFAULT 'done', created_at REAL);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, kind TEXT, payload TEXT, summary TEXT, status TEXT DEFAULT 'pending',
  source TEXT, created_at REAL, decided_at REAL);
CREATE TABLE IF NOT EXISTS model_configs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, owner_id INTEGER, name TEXT, provider TEXT, base_url TEXT, model TEXT, api_key TEXT,
  timeout INTEGER DEFAULT 60, max_tokens INTEGER DEFAULT 4096, caps TEXT DEFAULT '{}', enabled INTEGER DEFAULT 1,
  price_in REAL, price_out REAL, price_note TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS task_routes (user_id INTEGER, task TEXT, model_id INTEGER, PRIMARY KEY(user_id, task));
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, model_id INTEGER, task TEXT, status TEXT,
  prompt_tokens INTEGER, completion_tokens INTEGER, latency_ms INTEGER, error TEXT, created_at REAL, day TEXT);
CREATE TABLE IF NOT EXISTS resources (
  id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, url TEXT, platform TEXT, meta TEXT DEFAULT '{}',
  category_id INTEGER, created_at REAL, UNIQUE(user_id, url));
CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, action TEXT, target TEXT, detail TEXT, created_at REAL);
CREATE TABLE IF NOT EXISTS feedback (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, question_id TEXT, kind TEXT, text TEXT, status TEXT DEFAULT 'open', created_at REAL);
"""


def connect():
    c = getattr(_local, "conn", None)
    if c is None:
        os.makedirs(DATA_DIR, exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _local.conn = c
    return c


@contextmanager
def tx():
    c = connect()
    try:
        c.execute("BEGIN")
        yield c
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK")
        raise


def q(sql, args=()):
    return [dict(r) for r in connect().execute(sql, args).fetchall()]


def q1(sql, args=()):
    r = connect().execute(sql, args).fetchone()
    return dict(r) if r else None


def run(sql, args=()):
    c = connect()
    cur = c.execute(sql, args)
    c.commit()
    return cur.lastrowid


def J(v, default=None):
    if v is None:
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def dumps(v):
    return json.dumps(v, ensure_ascii=False)


def audit(user_id, action, target, detail=None):
    run("INSERT INTO audit(user_id, action, target, detail, created_at) VALUES (?,?,?,?,?)",
        (user_id, action, target, dumps(detail or {}), time.time()))


def init():
    c = connect()
    c.executescript(SCHEMA)
    cols = {r[1] for r in c.execute("PRAGMA table_info(messages)").fetchall()}
    if "status" not in cols:
        c.execute("ALTER TABLE messages ADD COLUMN status TEXT DEFAULT 'done'")
    # replies interrupted by a restart are closed so they don't look stuck
    c.execute("UPDATE messages SET status='done', content=COALESCE(content,'') || '\n（平台重启，这条回复没有生成完）' WHERE status='streaming'")
    c.commit()
    if not q1("SELECT 1 FROM users LIMIT 1"):
        run("INSERT INTO users(name, token, role, created_at) VALUES (?,?,?,?)",
            ("我", secrets.token_urlsafe(24), "admin", time.time()))


def local_user():
    return q1("SELECT * FROM users WHERE role='admin' ORDER BY id LIMIT 1")
