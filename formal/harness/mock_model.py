"""A loopback stand-in for the model endpoint, so harness checks need no model call.

It speaks just enough of the Responses API for Codex: the first request of a conversation
gets one tool call running a fixed shell command, and the next gets a closing message. It
records every request body, which shows what Codex really sends. Nothing leaves the machine.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CLOSING_MESSAGE = "Done."


def _event(kind: str, **fields) -> bytes:
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **fields})}\n\n".encode()


class MockModel:
    """`command` runs once per conversation, or `script` when given, as the body of a code-mode call. `requests` holds each body received."""

    def __init__(self, command: str, *, script: str | None = None) -> None:
        self.command = command
        self.script = script
        self.requests: list[dict] = []
        self.paths: list[str] = []
        self._lock = threading.Lock()
        mock = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args) -> None:
                pass

            def do_GET(self) -> None:
                with mock._lock:
                    mock.paths.append(f"GET {self.path}")
                self.send_response(404)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self) -> None:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                with mock._lock:
                    mock.paths.append(f"POST {self.path}")
                    mock.requests.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.end_headers()
                self.wfile.write(mock.reply(body))

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}/v1"
        threading.Thread(target=self._server.serve_forever, daemon=True).start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def reply(self, body: dict) -> bytes:
        answered = any(item.get("type") in ("custom_tool_call_output", "function_call_output") for item in body.get("input", []))
        response_id = f"resp_{len(self.requests)}"
        usage = {
            "input_tokens": 10, "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1, "output_tokens_details": {"reasoning_tokens": 0}, "total_tokens": 11,
        }
        if answered:
            item = {"type": "message", "role": "assistant", "id": "msg_1", "content": [{"type": "output_text", "text": CLOSING_MESSAGE}]}
        else:
            item = self._tool_call(body)
        return (
            _event("response.created", response={"id": response_id})
            + _event("response.output_item.done", item=item)
            + _event("response.completed", response={"id": response_id, "usage": usage})
        )

    def _tool_call(self, body: dict) -> dict:
        # Codex lists its tools in an `additional_tools` input item, under namespaces.
        text = json.dumps([item for item in body.get("input", []) if item.get("type") == "additional_tools"])
        if '"name": "exec"' in text:
            script = self.script or f"text(JSON.stringify(await tools.exec_command({{cmd: {json.dumps(self.command)}, max_output_tokens: 4000}})));"
            return {"type": "custom_tool_call", "id": "ctc_1", "status": "completed", "call_id": "call_1", "name": "exec", "input": script}
        return {"type": "function_call", "id": "fc_1", "status": "completed", "call_id": "call_1", "name": "exec_command", "arguments": json.dumps({"cmd": self.command})}
