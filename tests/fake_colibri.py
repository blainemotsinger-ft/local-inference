"""A fake Colibri server for testing the Claude Code scripts without a model.

It answers the two endpoints Claude Code uses, GET /v1/models and
POST /v1/messages (streaming or not), in Anthropic's format. Instead of
running a model, it plays back a script: each request that offers tools gets
the next step, which is either a tool call or a final text answer. Requests
without tools (Claude Code's background requests) get a short text answer
and do not use up a step.

Every request is recorded, so a test can check what Claude Code sent: the
model id, the API key header, the system prompt, the tools offered, and the
result of each tool call.

Use it from a test:

    with FakeColibri([tool("Bash", command="echo hi"), text("done")]) as fake:
        run(..., env={"COLIBRI_BASE_URL": fake.base_url})
        fake.tool_results()   # ["hi"]

Or by hand, with a script file holding a JSON list of steps:

    python3 tests/fake_colibri.py --port 8000 --script steps.json --log requests.jsonl
"""

import argparse
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL_ID = "qwen3.6-colibri"


def tool(name, **tool_input):
    """A step where the model calls a tool."""
    return {"tool": name, "input": tool_input}


def text(answer):
    """A step where the model gives its final answer."""
    return {"text": answer}


class FakeColibri:
    def __init__(self, script=None, port=0, log_path=None):
        self.script = list(script or [text("done")])
        self.requests = []
        self._step = 0
        self._lock = threading.Lock()
        self._log = open(log_path, "a", buffering=1) if log_path else None
        self._server = ThreadingHTTPServer(("127.0.0.1", port), self._handler())
        self._server.daemon_threads = True
        self._thread = None

    @property
    def port(self):
        return self._server.server_address[1]

    @property
    def base_url(self):
        """The OpenAI-style URL, the form COLIBRI_BASE_URL takes."""
        return f"http://127.0.0.1:{self.port}/v1"

    def start(self):
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._server.shutdown()
        self._server.server_close()
        if self._log:
            self._log.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    # What the tests read back.

    def messages_requests(self):
        return [r for r in self.requests if r["path"] == "/v1/messages"]

    def tool_results(self):
        """The text of every tool result Claude Code sent back, in order."""
        out = []
        for r in self.messages_requests():
            last = r["body"]["messages"][-1]
            if not isinstance(last.get("content"), list):
                continue
            for block in last["content"]:
                if block.get("type") == "tool_result":
                    out.append(_flatten(block.get("content")))
        return out

    def first_user_text(self):
        """The text of the first user message of the first request."""
        reqs = self.messages_requests()
        if not reqs:
            return ""
        return _flatten(reqs[0]["body"]["messages"][0].get("content"))

    # The server.

    def _next_step(self):
        with self._lock:
            step = self.script[min(self._step, len(self.script) - 1)]
            self._step += 1
            return self._step, step

    def _record(self, entry):
        with self._lock:
            self.requests.append(entry)
        if self._log:
            self._log.write(json.dumps(entry) + "\n")

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                pass

            def _record(self, body=None):
                fake._record({
                    "method": self.command,
                    "path": self.path.split("?")[0],
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": body,
                })

            def _json(self, code, obj):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self._record()
                if self.path.split("?")[0] == "/v1/models":
                    return self._json(200, {"data": [{"id": MODEL_ID, "type": "model"}]})
                self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": self.path}})

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._record(body)
                path = self.path.split("?")[0]
                if path == "/v1/messages/count_tokens":
                    return self._json(200, {"input_tokens": 100})
                if path != "/v1/messages":
                    return self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": path}})
                if body.get("tools"):
                    n, step = fake._next_step()
                else:
                    n, step = 0, text("ok")
                self._answer(body, n, step)

            def _answer(self, body, n, step):
                if "tool" in step:
                    block = {"type": "tool_use", "id": f"toolu_{n:04d}", "name": step["tool"], "input": {}}
                    delta = {"type": "input_json_delta", "partial_json": json.dumps(step["input"])}
                    full = dict(block, input=step["input"])
                    stop = "tool_use"
                else:
                    block = {"type": "text", "text": ""}
                    delta = {"type": "text_delta", "text": step["text"]}
                    full = {"type": "text", "text": step["text"]}
                    stop = "end_turn"
                message = {
                    "id": f"msg_{n:04d}", "type": "message", "role": "assistant",
                    "model": body.get("model"), "content": [],
                    "stop_reason": None, "stop_sequence": None,
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                }
                if not body.get("stream"):
                    return self._json(200, dict(message, content=[full], stop_reason=stop))

                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("connection", "close")
                self.end_headers()

                def event(kind, data):
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())

                event("message_start", {"type": "message_start", "message": message})
                event("content_block_start", {"type": "content_block_start", "index": 0, "content_block": block})
                event("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": delta})
                event("content_block_stop", {"type": "content_block_stop", "index": 0})
                event("message_delta", {"type": "message_delta",
                                        "delta": {"stop_reason": stop, "stop_sequence": None},
                                        "usage": {"output_tokens": 5}})
                event("message_stop", {"type": "message_stop"})
                self.wfile.flush()
                self.close_connection = True

        return Handler


def _flatten(content):
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return "\n".join(_flatten(c.get("text", c.get("content"))) if isinstance(c, dict) else str(c)
                     for c in content)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--script", help="JSON file: a list of steps, each {\"tool\": name, \"input\": {...}} or {\"text\": answer}")
    parser.add_argument("--log", help="append every request to this file as JSON lines")
    args = parser.parse_args()
    script = json.load(open(args.script)) if args.script else None
    fake = FakeColibri(script, port=args.port, log_path=args.log)
    print(f"fake Colibri at {fake.base_url}", file=sys.stderr)
    try:
        fake._server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
