"""Mock OpenAI-compatible and Anthropic endpoints for offline tests. Behaviour is driven by the prompt."""
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def decide(prompt_text, has_tool_result, tool_names):
    last_user = prompt_text.strip().splitlines()[-1] if prompt_text.strip() else ""
    if "请根据上面的信息" in last_user:
        return {"text": "补充回答：根据进度，先学完当前模块再刷题。"}
    if "空回复" in prompt_text:
        return {"tool": ("get_progress", {})} if not has_tool_result else {"text": ""}
    if "慢一点" in prompt_text:
        return {"text": "这是一段很长的分步回答。" * 12, "slow": True}
    if "只回复“连接正常”" in prompt_text:
        return {"text": "连接正常"}
    if "请调用 ping" in prompt_text:
        return {"tool": ("ping", {"ok": True})}
    if "请给下面的题目分类并分层" in prompt_text:
        ids = re.findall(r"id=([\w-]+)｜", prompt_text)
        cats = [int(x) for x in re.findall(r"^(\d+) ", prompt_text, re.M)]
        return {"text": json.dumps([{"id": i, "category": cats[k % len(cats)], "tier": k % 4 + 1, "score": 5, "points": ["模拟知识点"], "reason": "模拟理由"} for k, i in enumerate(ids)], ensure_ascii=False)}
    if "请拆出其中每一道完整的题" in prompt_text:
        return {"text": "```json\n" + json.dumps([
            {"type": "single", "title": "勾股定理", "stem": "直角三角形两直角边为 3 和 4，斜边是？", "options": ["5", "6", "7", "8"], "answer": "A", "analysis": "3²+4²=5²", "category": "几何", "tier": 1, "points": ["勾股定理"], "reason": "直接套公式"},
            {"type": "multi", "title": "质数", "stem": "下列哪些是质数？", "options": ["2", "4", "5", "9"], "answer": ["A", "C"], "category": "数论", "tier": 2},
            {"type": "judge", "title": "偶数", "stem": "0 是偶数。", "answer": "对", "tier": 1},
            {"type": "fill", "title": "圆周率", "stem": "圆周率约等于 ____（保留两位小数）", "answer": [["3.14"]], "tier": 1},
            {"type": "short", "title": "解释二分", "stem": "简述二分查找的前提和复杂度。", "answer": "数组有序；O(log n)", "tier": 2},
            {"type": "code", "title": "求和", "stem": "返回 a+b", "params": ["a", "b"], "examples": [{"input": "1,2", "output": "3", "args": [1, 2], "expect": 3}], "tier": 1}
        ], ensure_ascii=False) + "\n```"}
    if "请按评分标准给学生的简答题作答打分" in prompt_text:
        ratio = 1.0 if "有序" in prompt_text.split("学生作答：")[-1] else 0.3
        return {"text": json.dumps({"ratio": ratio, "hits": ["有序"], "misses": [], "reason": "模拟评分"}, ensure_ascii=False)}
    if "写一节 30–50 分钟的课程" in prompt_text:
        return {"text": json.dumps({"name": "x", "minutes": 35, "intro": "模拟课程", "concepts": [{"t": "概念一", "b": "正文", "code": "a+b"}],
                                    "signals": ["信号"], "templates": [{"t": "公式", "code": "c²=a²+b²"}], "example": {"id": "", "title": "例题", "stem": "题面", "steps": ["第一步"]},
                                    "pitfalls": ["坑"], "quiz": [{"q": "1+1=?", "o": ["1", "2"], "a": 1, "e": "2"}, {"q": "bad", "o": ["x"], "a": 5, "e": ""}]}, ensure_ascii=False)}
    if "调整我的计划" in prompt_text and not has_tool_result:
        return {"tool": ("propose_plan_change", {"changes": {"hours": 2.5}, "reason": "时间不够"})}
    if "今天做什么" in prompt_text and not has_tool_result and "get_today_plan" in tool_names:
        return {"tool": ("get_today_plan", {})}
    if has_tool_result:
        return {"text": "根据工具结果，我建议先完成今天的任务。已提出调整建议，请确认。"}
    return {"text": "你好，我是模拟模型。"}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send_sse(self, events, slow=False):
        import time as _t
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for e in events:
            if slow:
                _t.sleep(0.25)
            self.wfile.write(("data: %s\n\n" % (e if isinstance(e, str) else json.dumps(e, ensure_ascii=False))).encode("utf-8"))
            self.wfile.flush()

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n).decode("utf-8"))
        if self.path.endswith("/chat/completions"):
            if self.headers.get("Authorization") != "Bearer good-key":
                self.send_response(401); self.end_headers(); self.wfile.write(b'{"error":"bad key"}'); return
            msgs = body["messages"]
            text = "\n".join(m.get("content") or "" for m in msgs if isinstance(m.get("content"), str))
            has_tool = any(m["role"] == "tool" for m in msgs)
            tools = [t["function"]["name"] for t in body.get("tools") or []]
            d = decide(text, has_tool, tools)
            if not body.get("stream"):
                msg = {"role": "assistant", "content": d.get("text")}
                if "tool" in d:
                    msg["tool_calls"] = [{"id": "c1", "type": "function", "function": {"name": d["tool"][0], "arguments": json.dumps(d["tool"][1])}}]
                out = json.dumps({"choices": [{"message": msg}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out); return
            ev = []
            if "tool" in d:
                args = json.dumps(d["tool"][1], ensure_ascii=False)
                ev.append({"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "call_1", "function": {"name": d["tool"][0], "arguments": args[:5]}}]}}]})
                ev.append({"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": args[5:]}}]}}]})
            else:
                t = d["text"]
                for i in range(0, len(t), 7):
                    ev.append({"choices": [{"delta": {"content": t[i:i + 7]}}]})
            ev.append({"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8}})
            ev.append("[DONE]")
            self._send_sse(ev, slow=d.get("slow"))
        elif self.path.endswith("/v1/messages"):
            if self.headers.get("x-api-key") != "good-key":
                self.send_response(401); self.end_headers(); return
            text = (body.get("system") or "") + "\n" + "\n".join(m["content"] if isinstance(m["content"], str) else "" for m in body["messages"])
            has_tool = any(isinstance(m["content"], list) and any(b.get("type") == "tool_result" for b in m["content"]) for m in body["messages"])
            d = decide(text, has_tool, [t["name"] for t in body.get("tools") or []])
            if not body.get("stream"):
                content = [{"type": "text", "text": d.get("text", "")}]
                if "tool" in d:
                    content = [{"type": "tool_use", "id": "tu1", "name": d["tool"][0], "input": d["tool"][1]}]
                out = json.dumps({"content": content, "usage": {"input_tokens": 9, "output_tokens": 4}}).encode()
                self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out); return
            ev = [{"type": "message_start", "message": {"usage": {"input_tokens": 11}}}]
            if "tool" in d:
                ev.append({"type": "content_block_start", "index": 0, "content_block": {"type": "tool_use", "id": "tu_1", "name": d["tool"][0]}})
                a = json.dumps(d["tool"][1], ensure_ascii=False)
                ev.append({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": a[:4]}})
                ev.append({"type": "content_block_delta", "index": 0, "delta": {"type": "input_json_delta", "partial_json": a[4:]}})
            else:
                ev.append({"type": "content_block_start", "index": 0, "content_block": {"type": "text"}})
                for i in range(0, len(d["text"]), 6):
                    ev.append({"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": d["text"][i:i + 6]}})
            ev.append({"type": "message_delta", "usage": {"output_tokens": 7}})
            ev.append({"type": "message_stop"})
            self._send_sse(ev)
        else:
            self.send_response(404); self.end_headers()


def serve(port):
    s = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s


if __name__ == "__main__":
    serve(int(sys.argv[1]) if len(sys.argv) > 1 else 9911)
    threading.Event().wait()
