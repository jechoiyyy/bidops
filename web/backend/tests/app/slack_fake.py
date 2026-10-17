"""127.0.0.1에서 도는 가짜 Slack Web API (RL-01 T8·T9 공용).

실제 Slack에 닿지 않고 `slack_sdk.WebClient`의 실제 요청 경로(urllib → HTTP → 응답 검증)를
그대로 태우기 위한 서버다. 응답 모양은 Slack 공개 문서의 Web API 계약에서 가져왔다.

- 모든 응답은 HTTP 200 JSON `{"ok": bool, ...}`이며 실패는 `{"ok": false, "error": "<code>"}`.
  rate limit만 HTTP 429 + `Retry-After` 헤더 + `{"ok": false, "error": "ratelimited"}`.
- 인증: `Authorization: Bearer <token>`. 헤더가 없으면 `not_authed`, 다르면 `invalid_auth`
  (토큰을 본문 `token=`으로 보내는 옛 방식은 받지 않는다 — SDK는 헤더로 보낸다).
- `chat.postMessage` `{channel, text?, blocks?}` → `{"ok": true, "channel", "ts", "message": {...}}`.
  채널이 다르면 `channel_not_found`, text·blocks가 둘 다 없으면 `no_text`.
- `chat.update` `{channel, ts, text?, blocks?}` → `{"ok": true, "channel", "ts", "text", "message"}`.
  보낸 적 없는 ts는 `message_not_found`, 채널이 다르면 `channel_not_found`.
- `apps.connections.open`(app token) → `{"ok": true, "url": "wss://..."}`.

가짜가 아무 요청이나 받아 주면 결함을 굳힌다(CLAUDE.md "테스트 방향"). 그래서 토큰·채널·
ts를 실제 Slack처럼 검사하고, 틀리면 실제 Slack이 쓰는 error code로 거부한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from itertools import count
import json
import threading
from typing import Any
from urllib.parse import parse_qs


@dataclass
class FakeRequest:
    method: str
    authorization: str | None
    body: dict[str, Any]
    raw: str


@dataclass
class FakeSlack:
    bot_token: str
    channel: str
    app_token: str | None = None
    wss_url: str = "wss://wss-primary.slack.com/link/?ticket=fixture-ticket&app_id=A0FIXTURE"
    requests: list[FakeRequest] = field(default_factory=list)
    #: 다음 `chat.*` 호출에 돌려줄 실패 `(http_status, body)`. 비면 정상 처리한다.
    failures: list[tuple[int, dict[str, Any]]] = field(default_factory=list)
    posted: dict[str, dict[str, Any]] = field(default_factory=dict)
    _server: ThreadingHTTPServer | None = None
    _thread: threading.Thread | None = None
    _serial: Any = field(default_factory=lambda: count(1))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    @property
    def base_url(self) -> str:
        assert self._server is not None
        return f"http://127.0.0.1:{self._server.server_address[1]}/api/"

    def calls(self, method: str | None = None) -> list[FakeRequest]:
        return [request for request in self.requests if method is None or request.method == method]

    def start(self) -> FakeSlack:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args: Any) -> None:  # 요청 로그를 남기지 않는다
                return

            def do_POST(self) -> None:  # noqa: N802 - http.server 규약
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8") if length else ""
                content_type = self.headers.get("Content-Type") or ""
                if "json" in content_type:
                    body = json.loads(raw or "{}")
                else:
                    body = {key: values[0] for key, values in parse_qs(raw).items()}
                method = self.path.split("/api/", 1)[-1].split("?", 1)[0]
                request = FakeRequest(method, self.headers.get("Authorization"), body, raw)
                with fake._lock:
                    fake.requests.append(request)
                    status, payload, headers = fake._respond(request)
                encoded = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                for name, value in headers.items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(encoded)

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    # --- Slack 계약 -------------------------------------------------------------

    def _auth(self, request: FakeRequest, expected: str | None) -> str | None:
        if not request.authorization:
            return "not_authed"
        if expected is None or request.authorization != f"Bearer {expected}":
            return "invalid_auth"
        return None

    def _respond(self, request: FakeRequest) -> tuple[int, dict[str, Any], dict[str, str]]:
        if request.method == "apps.connections.open":
            error = self._auth(request, self.app_token)
            if error:
                return 200, {"ok": False, "error": error}, {}
            return 200, {"ok": True, "url": self.wss_url}, {}
        if request.method not in ("chat.postMessage", "chat.update"):
            return 200, {"ok": False, "error": "unknown_method"}, {}
        error = self._auth(request, self.bot_token)
        if error:
            return 200, {"ok": False, "error": error}, {}
        if self.failures:
            status, payload = self.failures.pop(0)
            headers = {"Retry-After": "30"} if status == 429 else {}
            return status, payload, headers
        body = request.body
        if body.get("channel") != self.channel:
            return 200, {"ok": False, "error": "channel_not_found"}, {}
        if not body.get("text") and not body.get("blocks"):
            return 200, {"ok": False, "error": "no_text"}, {}
        if request.method == "chat.postMessage":
            ts = f"1760572800.{next(self._serial):06d}"
            message = {
                "type": "message", "subtype": "bot_message", "bot_id": "B0FIXTURE", "ts": ts,
                "text": body.get("text", ""), "blocks": body.get("blocks", []),
            }
            self.posted[ts] = message
            return 200, {"ok": True, "channel": self.channel, "ts": ts, "message": message}, {}
        ts = body.get("ts")
        if ts not in self.posted:
            return 200, {"ok": False, "error": "message_not_found"}, {}
        message = {**self.posted[ts], "text": body.get("text", ""), "blocks": body.get("blocks", [])}
        self.posted[ts] = message
        return 200, {"ok": True, "channel": self.channel, "ts": ts, "text": body.get("text", ""),
                     "message": message}, {}


__all__ = ["FakeRequest", "FakeSlack"]
