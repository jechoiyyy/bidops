"""Slack 전송기 하나 (RL-01 spec "Slack"·"인터페이스" 외부 호출 보호 장치).

브리핑 메시지 전송(`chat.postMessage`), 버튼 반응 뒤 메시지 갱신(`chat.update`), 판정 완료 스레드
답글(`chat.postMessage` + `thread_ts`, RL-03), Socket Mode 연결(`apps.connections.open` → websocket)은
모두 이 모듈을 거친다. 다른 곳에서 `slack_sdk`
client를 직접 만들지 않는다.

호출 **전에** 차례로 검사하고 하나라도 어긋나면 네트워크에 닿지 않는다(fail closed).

1. `BIDOPS_SLACK_ENABLED`(기본 false) → `slack_disabled`
2. bot token(Socket Mode는 app token도) → `token_missing`
3. 채널 → `channel_missing`
4. 호출 URL host가 `BIDOPS_SLACK_ALLOWED_HOSTS`에 정확히 있는가 → `host_not_allowed`.
   Socket Mode가 받은 websocket 주소도 연결 전에 같은 목록으로 검사한다.

설정한 채널 하나에만 보내고 갱신한다. 다른 채널·hosted fallback·재시도용 다른 경로는 없다.
토큰은 `SecretStr`로만 들고 다니며 로그·응답·오류·예외 문자열에 넣지 않는다. Slack 오류는
안전한 code(`slack_api_error:<error>`·`slack_transport_error` 등)로만 바꾸고 원래 예외는
연결하지 않는다(`__cause__`·`__context__` 없음).

core는 도메인을 모른다. 무엇을 보낼지(블록·허용 키)는 호출자(lifecycle)가 넘긴다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
import ipaddress
import logging
import re
from typing import Any
from urllib.parse import urlsplit

from pydantic import SecretStr

#: Slack Web API 기준 주소. 설정 키가 아니라 코드 상수다(spec 설정 키 표에 없음).
SLACK_API_BASE_URL = "https://slack.com/api/"
#: `BIDOPS_SLACK_ALLOWED_HOSTS` 기본값(spec 설정 키 표).
DEFAULT_SLACK_ALLOWED_HOSTS = "slack.com,wss-primary.slack.com"

#: 전송하지 않은 사유(`slack.skipped_reason`)의 전송기 몫. 검사 순서와 같다.
SKIP_SLACK_DISABLED = "slack_disabled"
SKIP_TOKEN_MISSING = "token_missing"
SKIP_CHANNEL_MISSING = "channel_missing"
SKIP_HOST_NOT_ALLOWED = "host_not_allowed"
PREFLIGHT_REASONS = (
    SKIP_SLACK_DISABLED,
    SKIP_TOKEN_MISSING,
    SKIP_CHANNEL_MISSING,
    SKIP_HOST_NOT_ALLOWED,
)

_SAFE_ERROR = re.compile(r"[^a-z0-9_]")
_LOOPBACK_NAMES = frozenset({"localhost"})
_REDACTED = "[비밀 값]"


class SlackTransportError(RuntimeError):
    """안전한 code 하나만 담는 전송 실패. 토큰·URL·응답 본문을 담지 않는다."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    def __repr__(self) -> str:
        return f"SlackTransportError({self.code!r})"


def parse_allowed_hosts(value: str | Iterable[str]) -> tuple[str, ...]:
    """쉼표 목록 → 소문자 host 튜플. 빈 값은 빈 튜플(아무 host도 허용하지 않음)."""

    items = value.split(",") if isinstance(value, str) else list(value)
    hosts: list[str] = []
    for item in items:
        host = str(item).strip().lower().rstrip(".")
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


def _is_loopback(host: str) -> bool:
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def url_host_allowed(url: str, allowed_hosts: Sequence[str], *, secure_scheme: str) -> bool:
    """host가 허용 목록에 **정확히** 있고 scheme이 맞는가.

    `slack.com`을 허용해도 `evil.slack.com`이나 `slack.com.example`은 허용되지 않는다(부분
    일치 없음). scheme은 `https`/`wss`만 받는다. 평문(`http`/`ws`)은 host가 loopback이고
    그 loopback이 허용 목록에 명시돼 있을 때만 받는다 — 외부로 나가지 않는 격리 검사용이다.
    """

    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").lower().rstrip(".")
        _ = parts.port  # 잘못된 port는 ValueError
    except ValueError:
        return False
    if not host or host not in allowed_hosts:
        return False
    if parts.username or parts.password:
        return False
    plain = {"https": "http", "wss": "ws"}[secure_scheme]
    if parts.scheme == secure_scheme:
        return True
    return parts.scheme == plain and _is_loopback(host)


@dataclass(frozen=True)
class SlackSettings:
    """전송기 입력. 토큰은 `SecretStr`이라 repr·str에 값이 나오지 않는다."""

    enabled: bool
    bot_token: SecretStr = field(repr=False)
    app_token: SecretStr = field(repr=False)
    channel_id: str
    allowed_hosts: tuple[str, ...]

    @classmethod
    def from_settings(cls, settings: Any) -> SlackSettings:
        return cls(
            enabled=bool(settings.slack_enabled),
            bot_token=settings.slack_bot_token,
            app_token=settings.slack_app_token,
            channel_id=str(settings.slack_channel_id or "").strip(),
            allowed_hosts=parse_allowed_hosts(settings.slack_allowed_hosts),
        )

    def secrets(self) -> tuple[str, ...]:
        """가림 대상 실제 값(빈 값 제외)."""

        values = (self.bot_token.get_secret_value(), self.app_token.get_secret_value())
        return tuple(value for value in values if value.strip())


def redact(text: str, secrets: Iterable[str]) -> str:
    """알려진 비밀 값과 websocket ticket을 가린다."""

    masked = str(text)
    for secret in sorted({value for value in secrets if value}, key=len, reverse=True):
        masked = masked.replace(secret, _REDACTED)
    masked = re.sub(r"(?i)(ticket=)[^\s&]+", r"\1" + _REDACTED, masked)
    return re.sub(r"xox[a-z]-[A-Za-z0-9-]+", _REDACTED, masked)


class SecretRedactingFilter(logging.Filter):
    """`slack_sdk`에 넘기는 logger에 붙인다. 메시지와 인자를 문자열로 바꿔 가린다."""

    def __init__(self, secrets: Iterable[str]) -> None:
        super().__init__()
        self._secrets = tuple(secrets)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # pragma: no cover - 형식 오류 로그도 가린 채 남긴다
            message = str(record.msg)
        record.msg = redact(message, self._secrets)
        record.args = None
        record.exc_text = None
        if record.exc_info:
            # traceback에는 외부 예외 문자열이 실린다. 종류만 남긴다.
            record.msg = f"{record.msg} ({record.exc_info[0].__name__ if record.exc_info[0] else 'error'})"
            record.exc_info = None
        return True


def sdk_logger(name: str, secrets: Iterable[str]) -> logging.Logger:
    """`slack_sdk` client에 넘길 logger. 비밀 값 가림 filter를 한 번만 붙인다."""

    logger = logging.getLogger(name)
    for existing in list(logger.filters):
        if isinstance(existing, SecretRedactingFilter):
            logger.removeFilter(existing)
    logger.addFilter(SecretRedactingFilter(secrets))
    return logger


def _walk_keys(value: Any, keys: set[str]) -> set[str]:
    if isinstance(value, Mapping):
        keys.update(str(key) for key in value)
        for item in value.values():
            _walk_keys(item, keys)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _walk_keys(item, keys)
    return keys


def _api_error_code(error: Any) -> str:
    response = getattr(error, "response", None)
    raw = None
    try:
        raw = response.get("error") if response is not None else None
    except Exception:
        raw = None
    safe = _SAFE_ERROR.sub("", str(raw or "").lower())[:64]
    return f"slack_api_error:{safe}" if safe else "slack_api_error"


class SlackSender:
    """설정 하나에 묶인 전송기. 모든 호출이 같은 검사(`preflight`)를 먼저 통과한다."""

    def __init__(
        self,
        config: SlackSettings,
        *,
        base_url: str | None = None,
        timeout: float = 10.0,
        logger_name: str = "app.core.slack.sdk",
    ) -> None:
        self._config = config
        self._base_url = base_url if base_url is not None else SLACK_API_BASE_URL
        self._timeout = timeout
        self._logger_name = logger_name
        self._client: Any = None

    @classmethod
    def from_settings(cls, settings: Any, *, base_url: str | None = None) -> SlackSender:
        return cls(SlackSettings.from_settings(settings), base_url=base_url)

    def __repr__(self) -> str:
        return f"SlackSender(enabled={self._config.enabled!r}, channel_present={bool(self._config.channel_id)!r})"

    @property
    def channel_id(self) -> str:
        return self._config.channel_id

    @property
    def base_url(self) -> str:
        return self._base_url

    def secrets(self) -> tuple[str, ...]:
        return self._config.secrets()

    # --- 검사 -------------------------------------------------------------------

    def preflight(self, *, require_app_token: bool = False) -> str | None:
        """보내도 되면 `None`, 아니면 사유 code. 네트워크에 닿지 않는다."""

        config = self._config
        if not config.enabled:
            return SKIP_SLACK_DISABLED
        if not config.bot_token.get_secret_value().strip():
            return SKIP_TOKEN_MISSING
        if require_app_token and not config.app_token.get_secret_value().strip():
            return SKIP_TOKEN_MISSING
        if not config.channel_id:
            return SKIP_CHANNEL_MISSING
        if not url_host_allowed(self._base_url, config.allowed_hosts, secure_scheme="https"):
            return SKIP_HOST_NOT_ALLOWED
        return None

    def websocket_url_allowed(self, url: str) -> bool:
        return url_host_allowed(url, self._config.allowed_hosts, secure_scheme="wss")

    def _require_ready(self, *, require_app_token: bool = False) -> None:
        reason = self.preflight(require_app_token=require_app_token)
        if reason is not None:
            raise SlackTransportError(reason)

    @staticmethod
    def _check_payload(blocks: Sequence[Mapping[str, Any]], text: str, allowed_keys: frozenset[str]) -> None:
        if not isinstance(text, str) or not isinstance(blocks, (list, tuple)):
            raise SlackTransportError("payload_invalid")
        extra = _walk_keys(list(blocks), set()) - set(allowed_keys)
        if extra:
            raise SlackTransportError("payload_key_not_allowed")

    def _web_client(self) -> Any:
        if self._client is None:
            from slack_sdk import WebClient

            self._client = WebClient(
                token=self._config.bot_token.get_secret_value(),
                base_url=self._base_url,
                timeout=int(max(self._timeout, 1)),
                logger=sdk_logger(self._logger_name, self.secrets()),
            )
        return self._client

    def _call(self, method: str, **kwargs: Any) -> Mapping[str, Any]:
        """`slack_sdk` 호출 하나. 예외는 안전한 code로만 바꾸고 원래 예외를 잇지 않는다."""

        error_code: str | None = None
        data: Any = None
        try:
            from slack_sdk.errors import SlackApiError
        except ImportError:  # pragma: no cover - 이미지에는 lock으로 설치된다
            raise SlackTransportError("slack_sdk_missing") from None
        try:
            response = getattr(self._web_client(), method)(**kwargs)
            data = response.data
        except SlackApiError as error:
            error_code = _api_error_code(error)
        except Exception:
            error_code = "slack_transport_error"
        if error_code is not None:
            # except 블록 밖에서 올린다: `__context__`에 외부 예외(응답·URL)가 남지 않는다.
            raise SlackTransportError(error_code)
        if not isinstance(data, Mapping) or data.get("ok") is not True:
            raise SlackTransportError("slack_invalid_response")
        return data

    # --- Web API ----------------------------------------------------------------

    def post_message(
        self,
        *,
        blocks: Sequence[Mapping[str, Any]],
        text: str,
        allowed_keys: frozenset[str],
    ) -> str:
        """설정한 채널에 메시지 하나를 보내고 ts를 돌려준다."""

        self._require_ready()
        self._check_payload(blocks, text, allowed_keys)
        data = self._call(
            "chat_postMessage", channel=self._config.channel_id, blocks=list(blocks), text=text
        )
        ts = data.get("ts")
        if not isinstance(ts, str) or not ts.strip():
            raise SlackTransportError("slack_invalid_response")
        return ts

    def update_message(
        self,
        *,
        channel: str,
        ts: str,
        blocks: Sequence[Mapping[str, Any]],
        text: str,
        allowed_keys: frozenset[str],
    ) -> None:
        """설정한 채널의 메시지만 갱신한다. 다른 채널은 호출 전에 거부한다."""

        self._require_ready()
        if channel != self._config.channel_id:
            raise SlackTransportError("channel_not_allowed")
        if not isinstance(ts, str) or not ts.strip():
            raise SlackTransportError("payload_invalid")
        self._check_payload(blocks, text, allowed_keys)
        self._call("chat_update", channel=channel, ts=ts, blocks=list(blocks), text=text)

    def post_thread_reply(self, *, channel: str, thread_ts: str, text: str) -> str:
        """설정한 채널의 메시지 스레드에 글 한 줄을 달고 답글 ts를 돌려준다 (RL-03 "Slack 스레드").

        `post_message`와 같은 검사(`preflight`: 켜짐·토큰·채널·allowlist)를 호출 전에 하고, 다른
        채널은 `update_message`처럼 호출 전에 거부한다. 블록 없이 대체 텍스트 한 줄만 보낸다 —
        무엇을 쓸지는 호출자가 정하고 이 전송기는 도메인을 모른다.
        """

        self._require_ready()
        if channel != self._config.channel_id:
            raise SlackTransportError("channel_not_allowed")
        if not isinstance(thread_ts, str) or not thread_ts.strip():
            raise SlackTransportError("payload_invalid")
        if not isinstance(text, str) or not text.strip():
            raise SlackTransportError("payload_invalid")
        data = self._call("chat_postMessage", channel=channel, thread_ts=thread_ts, text=text)
        ts = data.get("ts")
        if not isinstance(ts, str) or not ts.strip():
            raise SlackTransportError("slack_invalid_response")
        return ts

    # --- Socket Mode ------------------------------------------------------------

    def socket_mode_client(
        self,
        listener: Callable[[Any, Any], None],
        *,
        logger_name: str = "app.core.slack.socket",
    ) -> Any:
        """websocket 주소를 받은 뒤 연결 **전에** host를 검사하는 Socket Mode client.

        `apps.connections.open`은 Web API(같은 기준 주소·같은 검사)로 부른다. 받은 주소의
        host가 허용 목록에 없으면 연결하지 않고 `SlackTransportError("host_not_allowed")`.
        재연결(`connect_to_new_endpoint`)도 같은 메서드를 거치므로 같은 검사를 받는다.
        """

        self._require_ready(require_app_token=True)
        from slack_sdk import WebClient
        from slack_sdk.socket_mode.builtin import SocketModeClient

        sender = self
        logger = sdk_logger(logger_name, self.secrets())

        class _GuardedSocketModeClient(SocketModeClient):
            def issue_new_wss_url(self) -> str:  # type: ignore[override]
                sender._require_ready(require_app_token=True)
                error_code: str | None = None
                url: Any = None
                try:
                    url = super().issue_new_wss_url()
                except Exception:
                    error_code = "slack_transport_error"
                if error_code is not None:
                    raise SlackTransportError(error_code)
                if not isinstance(url, str) or not sender.websocket_url_allowed(url):
                    raise SlackTransportError(SKIP_HOST_NOT_ALLOWED)
                return url

        client = _GuardedSocketModeClient(
            app_token=self._config.app_token.get_secret_value(),
            logger=logger,
            # Socket Mode의 Web API client는 app token만 쓴다(bot token을 싣지 않는다).
            web_client=WebClient(token=None, base_url=self._base_url, logger=logger),
            auto_reconnect_enabled=True,
        )
        client.socket_mode_request_listeners.append(listener)
        return client


__all__ = [
    "DEFAULT_SLACK_ALLOWED_HOSTS",
    "PREFLIGHT_REASONS",
    "SKIP_CHANNEL_MISSING",
    "SKIP_HOST_NOT_ALLOWED",
    "SKIP_SLACK_DISABLED",
    "SKIP_TOKEN_MISSING",
    "SLACK_API_BASE_URL",
    "SecretRedactingFilter",
    "SlackSender",
    "SlackSettings",
    "SlackTransportError",
    "parse_allowed_hosts",
    "redact",
    "sdk_logger",
    "url_host_allowed",
]
