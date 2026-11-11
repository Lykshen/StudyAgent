"""Model adapters. Two protocols cover the providers: OpenAI-compatible (DeepSeek, Qwen, Kimi, GLM, OpenAI…)
and Anthropic Messages. Both support streaming and tool calling. Standard library only (urllib)."""
import json
import socket
import ssl
import time
import urllib.error
import urllib.request

from . import db

PRESETS = [
    {"key": "deepseek", "name": "DeepSeek", "provider": "openai_compat", "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
     "caps": {"tools": True, "stream": True, "json": True, "vision": False, "stream_usage": True}},
    {"key": "qwen", "name": "通义千问", "provider": "openai_compat", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus",
     "caps": {"tools": True, "stream": True, "json": True, "vision": False, "stream_usage": True}},
    {"key": "kimi", "name": "Kimi（月之暗面）", "provider": "openai_compat", "base_url": "https://api.moonshot.cn/v1", "model": "moonshot-v1-8k",
     "caps": {"tools": True, "stream": True, "json": False, "vision": False, "stream_usage": False}},
    {"key": "glm", "name": "智谱 GLM", "provider": "openai_compat", "base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4-flash",
     "caps": {"tools": True, "stream": True, "json": False, "vision": False, "stream_usage": False}},
    {"key": "openai", "name": "OpenAI", "provider": "openai_compat", "base_url": "https://api.openai.com/v1", "model": "gpt-4o-mini",
     "caps": {"tools": True, "stream": True, "json": True, "vision": True, "stream_usage": True}},
    {"key": "claude", "name": "Claude（Anthropic）", "provider": "anthropic", "base_url": "https://api.anthropic.com", "model": "claude-sonnet-5-5",
     "caps": {"tools": True, "stream": True, "json": False, "vision": True}},
    {"key": "custom", "name": "其它 OpenAI 兼容服务（含本地模型）", "provider": "openai_compat", "base_url": "http://localhost:11434/v1", "model": "",
     "caps": {"tools": False, "stream": True, "json": False, "vision": False, "stream_usage": False}},
]

TASKS = {"chat": "问答与讲解", "plan": "学习计划", "classify": "分类分层", "import": "导入题目", "grade": "主观题评分", "lesson": "生成课程"}


class Cancelled(Exception):
    """Raised from a streaming callback when the client went away / pressed stop."""


class LLMError(Exception):
    def __init__(self, msg, code="error", retryable=False):
        super().__init__(msg)
        self.code, self.retryable = code, retryable


def _friendly(status, body):
    text = (body or "")[:300]
    if status in (401, 403):
        return LLMError("认证失败：API Key 无效、过期或没有这个模型的权限（%d）" % status, "auth")
    if status == 402 or "insufficient" in text.lower() or "balance" in text.lower():
        return LLMError("账户余额不足或额度用完（%d）" % status, "quota")
    if status == 429:
        return LLMError("请求太频繁或达到限流，请稍后再试（429）", "rate_limited", True)
    if status == 404:
        return LLMError("接口地址或模型名不对（404）：%s" % text, "not_found")
    if status >= 500:
        return LLMError("模型服务暂时不可用（%d）" % status, "server", True)
    return LLMError("请求被拒绝（%d）：%s" % (status, text), "bad_request")


def _post(url, headers, payload, timeout, stream):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST", headers={"Content-Type": "application/json", **headers})
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            body = ""
        raise _friendly(e.code, body)
    except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as e:
        reason = getattr(e, "reason", e)
        if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason):
            raise LLMError("连接模型服务超时，请检查网络或调大超时时间", "timeout", True)
        raise LLMError("连不上模型服务：%s（检查地址和网络）" % reason, "network", True)


def _sse_lines(resp):
    for raw in resp:
        line = raw.decode("utf-8", "replace").strip()
        if line.startswith("data:"):
            yield line[5:].strip()


# ---------------- OpenAI-compatible ----------------
def _oa_messages(messages):
    out = []
    for m in messages:
        if m["role"] == "assistant" and m.get("tool_calls"):
            out.append({"role": "assistant", "content": m.get("content") or None,
                        "tool_calls": [{"id": tc["id"], "type": "function",
                                        "function": {"name": tc["name"], "arguments": json.dumps(tc.get("arguments") or {}, ensure_ascii=False)}}
                                       for tc in m["tool_calls"]]})
        elif m["role"] == "tool":
            out.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m["content"]})
    return out


def _openai_chat(cfg, messages, tools, on_text, json_mode, max_tokens, on_reason=None):
    caps = db.J(cfg.get("caps"), {}) or {}
    stream = bool(on_text) and caps.get("stream", True)
    payload = {"model": cfg["model"], "messages": _oa_messages(messages), "max_tokens": max_tokens}
    if tools and caps.get("tools", True):
        payload["tools"] = [{"type": "function", "function": {"name": t["name"], "description": t["description"], "parameters": t["parameters"]}} for t in tools]
    if json_mode and caps.get("json"):
        payload["response_format"] = {"type": "json_object"}
    if stream:
        payload["stream"] = True
        if caps.get("stream_usage"):
            payload["stream_options"] = {"include_usage": True}
    headers = {"Authorization": "Bearer " + (cfg.get("api_key") or "")}
    resp = _post(cfg["base_url"].rstrip("/") + "/chat/completions", headers, payload, cfg.get("timeout") or 60, stream)
    if not stream:
        j = json.loads(resp.read().decode("utf-8"))
        msg = (j.get("choices") or [{}])[0].get("message", {})
        tcs = [{"id": tc.get("id") or "call_%d" % i, "name": tc["function"]["name"], "arguments": _loads(tc["function"].get("arguments"))}
               for i, tc in enumerate(msg.get("tool_calls") or [])]
        u = j.get("usage") or {}
        if on_text and msg.get("content"):
            on_text(msg["content"])
        return {"content": msg.get("content") or "", "tool_calls": tcs, "usage": {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}}
    text, calls, usage = [], {}, {}
    for data in _sse_lines(resp):
        if data == "[DONE]":
            break
        try:
            j = json.loads(data)
        except Exception:
            continue
        if j.get("usage"):
            usage = {"in": j["usage"].get("prompt_tokens"), "out": j["usage"].get("completion_tokens")}
        for ch in j.get("choices") or []:
            d = ch.get("delta") or {}
            if d.get("reasoning_content") and on_reason:
                on_reason(d["reasoning_content"])
            if d.get("content"):
                text.append(d["content"])
                on_text(d["content"])
            for tc in d.get("tool_calls") or []:
                slot = calls.setdefault(tc.get("index", 0), {"id": None, "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] += fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]
    tcs = [{"id": s["id"] or "call_%d" % i, "name": s["name"], "arguments": _loads(s["args"])} for i, s in sorted(calls.items())]
    return {"content": "".join(text), "tool_calls": tcs, "usage": usage}


# ---------------- Anthropic ----------------
def _an_messages(messages):
    system, out = [], []
    for m in messages:
        if m["role"] == "system":
            system.append(m["content"])
        elif m["role"] == "assistant":
            blocks = []
            if m.get("content"):
                blocks.append({"type": "text", "text": m["content"]})
            for tc in m.get("tool_calls") or []:
                blocks.append({"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": tc.get("arguments") or {}})
            out.append({"role": "assistant", "content": blocks or [{"type": "text", "text": ""}]})
        elif m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            if out and out[-1]["role"] == "user" and isinstance(out[-1]["content"], list) and out[-1]["content"] and out[-1]["content"][0].get("type") == "tool_result":
                out[-1]["content"].append(block)
            else:
                out.append({"role": "user", "content": [block]})
        else:
            out.append({"role": "user", "content": m["content"]})
    return "\n\n".join(system), out


def _anthropic_chat(cfg, messages, tools, on_text, json_mode, max_tokens, on_reason=None):
    caps = db.J(cfg.get("caps"), {}) or {}
    stream = bool(on_text) and caps.get("stream", True)
    system, msgs = _an_messages(messages)
    payload = {"model": cfg["model"], "max_tokens": max_tokens, "messages": msgs}
    if system:
        payload["system"] = system
    if tools and caps.get("tools", True):
        payload["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
    if stream:
        payload["stream"] = True
    headers = {"x-api-key": cfg.get("api_key") or "", "anthropic-version": "2023-06-01"}
    resp = _post(cfg["base_url"].rstrip("/") + "/v1/messages", headers, payload, cfg.get("timeout") or 60, stream)
    if not stream:
        j = json.loads(resp.read().decode("utf-8"))
        text = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        tcs = [{"id": b["id"], "name": b["name"], "arguments": b.get("input") or {}} for b in j.get("content", []) if b.get("type") == "tool_use"]
        if on_text and text:
            on_text(text)
        u = j.get("usage") or {}
        return {"content": text, "tool_calls": tcs, "usage": {"in": u.get("input_tokens"), "out": u.get("output_tokens")}}
    text, blocks, usage = [], {}, {}
    for data in _sse_lines(resp):
        try:
            j = json.loads(data)
        except Exception:
            continue
        t = j.get("type")
        if t == "message_start":
            usage["in"] = ((j.get("message") or {}).get("usage") or {}).get("input_tokens")
        elif t == "content_block_start":
            b = j.get("content_block") or {}
            blocks[j.get("index", 0)] = {"type": b.get("type"), "id": b.get("id"), "name": b.get("name"), "json": ""}
        elif t == "content_block_delta":
            d = j.get("delta") or {}
            if d.get("type") == "thinking_delta" and on_reason:
                on_reason(d.get("thinking", ""))
            if d.get("type") == "text_delta":
                text.append(d.get("text", ""))
                on_text(d.get("text", ""))
            elif d.get("type") == "input_json_delta":
                blocks.setdefault(j.get("index", 0), {"type": "tool_use", "json": ""})["json"] += d.get("partial_json", "")
        elif t == "message_delta":
            usage["out"] = (j.get("usage") or {}).get("output_tokens")
        elif t == "error":
            raise LLMError("模型服务返回错误：%s" % (j.get("error") or {}).get("message", ""), "server", True)
    tcs = [{"id": b["id"], "name": b["name"], "arguments": _loads(b["json"]) or {}} for _, b in sorted(blocks.items()) if b.get("type") == "tool_use"]
    return {"content": "".join(text), "tool_calls": tcs, "usage": usage}


def _loads(s):
    if isinstance(s, dict):
        return s
    try:
        return json.loads(s) if s else {}
    except Exception:
        return {"_raw": s}


def chat(cfg, messages, tools=None, on_text=None, json_mode=False, max_tokens=None, user_id=None, task="chat", on_reason=None):
    """Call a model once. Records a usage row (success or failure). Raises LLMError."""
    if not cfg:
        raise LLMError("还没有配置可用的模型。到「模型」页面添加一个，填好 API Key 并测试连接。", "no_model")
    if not cfg.get("enabled", 1):
        raise LLMError("这个模型已被停用", "disabled")
    max_tokens = max_tokens or cfg.get("max_tokens") or 4096
    t0 = time.time()
    fn = _anthropic_chat if cfg["provider"] == "anthropic" else _openai_chat
    try:
        out = fn(cfg, messages, tools, on_text, json_mode, max_tokens, on_reason)
        record_usage(user_id, cfg["id"], task, "ok", out.get("usage") or {}, t0)
        return out
    except Cancelled:
        record_usage(user_id, cfg["id"], task, "cancelled", {}, t0)
        raise
    except LLMError as e:
        record_usage(user_id, cfg["id"], task, e.code, {}, t0, str(e))
        raise
    except Exception as e:  # unexpected parse errors etc.
        record_usage(user_id, cfg["id"], task, "error", {}, t0, str(e)[:200])
        raise LLMError("调用模型时出错：%s" % e, "error")


def record_usage(user_id, model_id, task, status, usage, t0, error=None):
    try:
        db.run("""INSERT INTO usage(user_id, model_id, task, status, prompt_tokens, completion_tokens, latency_ms, error, created_at, day)
                  VALUES (?,?,?,?,?,?,?,?,?,date('now','localtime'))""",
               (user_id, model_id, task, status, usage.get("in"), usage.get("out"), int((time.time() - t0) * 1000), error, time.time()))
    except Exception:
        pass


def model_for(user_id, task):
    """Pick the model for a task: user's route → platform default (first enabled)."""
    r = db.q1("SELECT model_id FROM task_routes WHERE user_id=? AND task=?", (user_id, task)) or \
        db.q1("SELECT model_id FROM task_routes WHERE user_id=? AND task='chat'", (user_id,))
    if r:
        m = db.q1("SELECT * FROM model_configs WHERE id=? AND enabled=1 AND (owner_id IS NULL OR owner_id=?)", (r["model_id"], user_id))
        if m:
            return m
    return db.q1("SELECT * FROM model_configs WHERE enabled=1 AND (owner_id IS NULL OR owner_id=?) ORDER BY id LIMIT 1", (user_id,))


def get_model(model_id, user_id):
    return db.q1("SELECT * FROM model_configs WHERE id=? AND (owner_id IS NULL OR owner_id=?)", (model_id, user_id))


def public_model(m):
    k = m.get("api_key") or ""
    return {**{x: m[x] for x in ("id", "name", "provider", "base_url", "model", "timeout", "max_tokens", "enabled", "owner_id", "price_in", "price_out", "price_note")},
            "caps": db.J(m.get("caps"), {}), "key_hint": ("…" + k[-4:]) if len(k) >= 8 else ("已填写" if k else "未填写")}
