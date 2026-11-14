"""A stand-in for the OpenAI Responses API, enough for `codex exec`: it plays a list of tool calls.

Each request gets the next move as a function call, streamed as server-sent events; after the
last move it replies with a short message. Every request body is saved, so a test can check
what Codex sent (tool names, pictures in the tool outputs).

    python fake_responses.py PORT MOVES.json REQUESTS_DIR
"""
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT, MOVES, OUT = int(sys.argv[1]), json.loads(Path(sys.argv[2]).read_text()), Path(sys.argv[3])
OUT.mkdir(parents=True, exist_ok=True)
state = {"n": 0, "req": 0}


def tool_ref(tools, short):
    """Where Codex put the MCP tool `short`: (name, namespace or None). Codex groups MCP tools in a namespace."""
    for t in tools:
        if t.get("type") == "namespace":
            for inner in t.get("tools", []):
                if inner.get("name") == short:
                    return short, t["name"]
        elif t.get("name") == short:
            return short, None
    raise SystemExit(f"no tool {short!r}")


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"data":[]}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        state["req"] += 1
        (OUT / f"req_{state['req']:03d}.json").write_text(json.dumps(body))
        n = state["n"]
        state["n"] += 1
        rid = f"resp_{n}"
        if n < len(MOVES):
            tool, args = MOVES[n]
            name, ns = tool_ref(body.get("tools", []), tool)
            item = {"type": "function_call", "id": f"fc_{n}", "call_id": f"call_{n}",
                    "name": name, "arguments": json.dumps(args), "status": "completed"}
            if ns:
                item["namespace"] = ns
        else:
            item = {"type": "message", "id": f"msg_{n}", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "All done.", "annotations": []}]}
        usage = {"input_tokens": 100, "input_tokens_details": {"cached_tokens": 40}, "output_tokens": 7,
                 "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 107}
        events = [
            ("response.created", {"type": "response.created", "response": {"id": rid, "status": "in_progress"}}),
            ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": item}),
            ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item}),
            ("response.completed", {"type": "response.completed",
                                    "response": {"id": rid, "status": "completed", "output": [item], "usage": usage}}),
        ]
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        for name, data in events:
            self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
