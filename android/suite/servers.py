"""Host-side helper servers, reached from the emulator through `adb reverse`.

FakeSystemOne: a deterministic drop-in for POST /v1/systemone. It records each request and answers with a fixed
option text (or an HTTP error), so the suite can check the app's request (state text, model, question) end to end.
The "target" question (intent cursor mode) is answered by `target_answer(options) -> {choice, probabilities,
confidence}`. Port 8767 by default: 8765 is where the real local server (finetune/servers/systemone.py) listens.
WebServer: serves suite/www/ (a long page for the browser stand-in).
"""

from __future__ import annotations

import json
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from voxlib import adb

WWW = Path(__file__).resolve().parent / "www"


class FakeSystemOne:
    def __init__(self, port: int = 8767) -> None:
        self.port = port
        self.requests: list[dict] = []
        self.target_answer = lambda options: {"choice": options[-1], "probabilities": {options[-1]: 1.0}, "confidence": 1.0}
        self.headers: list[dict] = []
        self.answer = "swipe up"
        self.status = 200
        self.option_format = None   # when set, GET /health declares it (OptionFormat); None = no /health -> v1
        outer = self

        class H(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path == "/health" and outer.option_format:
                    body = json.dumps({"option_format": outer.option_format}).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self) -> None:  # noqa: N802
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.headers.append({k.lower(): v for k, v in self.headers.items()})
                try:
                    outer.requests.append(json.loads(body))
                except json.JSONDecodeError:
                    outer.requests.append({"_raw": body.decode(errors="replace")})
                if self.path != "/v1/systemone" or outer.status != 200:
                    self.send_response(404 if self.path != "/v1/systemone" else outer.status)
                    self.end_headers()
                    self.wfile.write(b'{"detail":"fake error"}')
                    return
                answers = {}
                for qid, q in outer.requests[-1].get("questions", {}).items():
                    if qid == "target":
                        answers[qid] = {"type": "choice", **outer.target_answer(list(q["criteria"]))}
                    else:
                        answers[qid] = {"type": "choice", "choice": outer.answer, "probabilities": {outer.answer: 0.97},
                                        "confidence": 0.95}
                out = json.dumps({"model": "fake-systemone", "answers": answers, "latency_ms": 1.0,
                                  "usage": {"input_tokens": 0, "output_tokens": 0}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

            def log_message(self, *a) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        adb("reverse", f"tcp:{port}", f"tcp:{port}")

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        adb("reverse", "--remove", f"tcp:{self.port}", check=False)


class WebServer:
    def __init__(self, port: int = 8766) -> None:
        self.port = port

        class Quiet(SimpleHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(Quiet, directory=str(WWW)))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        adb("reverse", f"tcp:{port}", f"tcp:{port}")

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/long.html"

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        adb("reverse", "--remove", f"tcp:{self.port}", check=False)
