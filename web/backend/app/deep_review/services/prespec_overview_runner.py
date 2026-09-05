"""사전규격 개요 검토의 모델 실행 (명세 §6.3).

큐 유입 → lease claim → 승인된 binding 한 번 호출 → 결정적 검증 → 완료/실패의
한 슬롯을 소유한다. **개요 전용 worker 진입점은 없다.** 이 runner는 합성
analysis worker의 한 poll 안에서만 돌고, 그 poll은 C-2·심층 검토·개요 중
하나만 잡는다.

경계 규칙:

- 승인된 binding이 없으면 아무것도 부르지 않고 review를 ``awaiting_model``에
  남긴다. 다른 주소·다른 provider로 넘어가지 않는다.
- 모델에는 snapshot 범위의 block text·page·ordinal·block_key만 보낸다. object
  key·경로·자격증명·회사 프로필은 이 경계를 넘지 않는다.
- 검증 실패는 자동 보정도 재프롬프트도 하지 않고 ``failed``로 닫는다.
- 실패한 attempt를 자동으로 다시 시작하지 않는다. 재실행은 사람이 만드는 새
  attempt다.
"""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.model_client import (
    ModelClient,
    ModelEndpointError,
    ModelIdentityError,
    ModelInvocationError,
)
from ...core.models import AuditEvent
from ...core.object_store import EncryptedModelResponseStore, ObjectStoreError
from .auto_preparation import maybe_auto_start_deep_review
from ..models import (
    ContentObject,
    ContentObjectLocation,
    PreSpecOverviewAttempt,
    PreSpecOverviewSnapshot,
)
from .prespec_overview import (
    OverviewAttemptError,
    OverviewModelBinding,
    OverviewPolicy,
    OverviewPolicyError,
    OverviewResultValidationError,
    OverviewScopeError,
    approved_overview_binding,
    build_overview_model_input,
    claim_overview_attempt,
    complete_overview_attempt,
    enqueue_overview_attempt,
    expire_overview_leases,
    fail_overview_attempt,
    load_overview_policy,
    overview_quality_status,
)


#: 호출 timeout 300초 × (1 + 재시도 2) + 여유. 이보다 짧으면 vLLM이 아직 승인된
#: 요청을 처리하는 중인 정상 worker가 만료로 회수된다.
OVERVIEW_LEASE_SECONDS = 1_200
#: policy가 이름 붙인 단일 stage. 실제 지시문은 policy 파일이 갖고 있고
#: runner는 ``policy.stage``를 그대로 쓴다 — 이 상수는 그 이름의 계약이다.
OVERVIEW_STAGE = "prespec_overview"
OVERVIEW_AUDIT_ACTION = "prespec_overview.attempt_run"
_SHA256 = re.compile(r"[0-9a-f]{64}")
_UNSET = object()


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class OverviewRunResult:
    """한 poll이 개요 슬롯에서 한 일. 원문·응답·경로는 담지 않는다."""

    claimed: bool
    attempt_id: UUID | None = None
    status: str = "idle"
    reason_code: str | None = None
    expired_leases: int = 0


class PreSpecOverviewRunner:
    """개요 attempt 하나를 끝까지 진행시키는 실행기.

    ``client``·``binding``을 주입하면 그대로 쓰고, 없으면 policy 파일과 용도별
    설정에서 해석한다. 해석이 실패하면 **부르지 않는다** — 이것이 fail closed의
    지점이다.
    """

    def __init__(
        self,
        *,
        client: Any | None = None,
        binding: OverviewModelBinding | None | Any = _UNSET,
        policy: OverviewPolicy | None = None,
        raw_response_store: Any | None = None,
        root: Path | None = None,
        lease_seconds: int = OVERVIEW_LEASE_SECONDS,
        settings: Any | None = None,
        deep_review_service: Any | None = None,
        clock: Callable[[], datetime] = _now,
    ) -> None:
        self._client = client
        self._binding = binding
        self._policy = policy
        self._policy_loaded = policy is not None
        self._raw_response_store = raw_response_store
        # §6.4의 자동 시작이 부르는 심층 검토 서비스. 없으면 필요한 순간에
        # 기본 서비스를 만든다 — 개요 실행 경로가 그 설정에 묶이지 않는다.
        self._deep_review_service = deep_review_service
        self.root = root
        self.lease_seconds = max(int(lease_seconds), 1)
        self.settings = settings
        self.clock = clock
        self._resolved: tuple[OverviewModelBinding | None, Any] | None = None

    # -- binding 해석 --------------------------------------------------
    def policy(self) -> OverviewPolicy | None:
        if not self._policy_loaded:
            try:
                self._policy = load_overview_policy()
            except OverviewPolicyError:
                self._policy = None
            self._policy_loaded = True
        return self._policy

    def _resolve(self) -> tuple[OverviewModelBinding | None, Any]:
        """(binding, client)를 한 번만 해석하고 둘 다 있을 때만 돌려준다."""

        if self._resolved is not None:
            return self._resolved
        client = self._client
        binding = None if self._binding is _UNSET else self._binding
        policy = self.policy()
        if policy is None:
            self._resolved = (None, None)
            return self._resolved
        try:
            if client is None:
                client = ModelClient.for_purpose(
                    "overview",
                    model=policy.model_name,
                    output_contract=policy.output_contract,
                    settings=self.settings,
                    verify_identity=False,
                )
            if self._binding is _UNSET:
                binding = approved_overview_binding(
                    policy=policy,
                    identity=getattr(client, "verify_identity", None),
                    settings=self.settings,
                )
        except (ModelEndpointError, ModelIdentityError, ValueError, OSError):
            binding, client = None, None
        if binding is None or client is None:
            # binding이 없으면 client도 들고 있지 않는다. 승인 없이 열려 있는
            # 주소를 남겨 두지 않는다는 뜻이다.
            self._resolved = (None, None)
        else:
            self._resolved = (binding, client)
        return self._resolved

    # -- 한 poll -------------------------------------------------------
    def run_once(self, session: Session, worker_id: str) -> OverviewRunResult:
        """만료 lease 회수 → 큐 유입 → claim → 실행을 한 번씩 한다."""

        now = self.clock()
        expired = expire_overview_leases(session, now=now, actor_id=worker_id)
        if expired:
            session.commit()
        binding, client = self._resolve()
        if binding is None or client is None:
            return OverviewRunResult(False, expired_leases=len(expired))

        if enqueue_overview_attempt(session, binding) is not None:
            session.commit()
        attempt = claim_overview_attempt(
            session,
            worker_id,
            lease_seconds=self.lease_seconds,
            now=self.clock(),
        )
        if attempt is None:
            return OverviewRunResult(False, expired_leases=len(expired))
        attempt_id = attempt.id
        snapshot = session.get(PreSpecOverviewSnapshot, attempt.snapshot_id)
        notice_id = int(snapshot.notice_id) if snapshot is not None else None
        review_id = attempt.review_id
        sequence = int(attempt.sequence)
        quality_status = overview_quality_status(attempt)

        # 입력은 claim과 같은 transaction에서 동결한다. 모델 호출은 그 뒤에
        # 열린 transaction 없이 수행한다.
        try:
            if snapshot is None:
                raise OverviewAttemptError("input_unavailable")
            blocks = build_overview_model_input(session, snapshot, root=self.root)
        except (OverviewAttemptError, OverviewScopeError) as error:
            session.commit()
            return self._fail(
                session,
                attempt_id,
                worker_id,
                error.code,
                notice_id=notice_id,
                review_id=review_id,
                sequence=sequence,
                quality_status=quality_status,
            )
        session.commit()

        try:
            output, raw = self._invoke(client, blocks)
        except ModelInvocationError as error:
            return self._fail(
                session,
                attempt_id,
                worker_id,
                error.code,
                notice_id=notice_id,
                review_id=review_id,
                sequence=sequence,
                quality_status=quality_status,
            )
        except (ModelIdentityError, OverviewAttemptError) as error:
            return self._fail(
                session,
                attempt_id,
                worker_id,
                error.code,
                notice_id=notice_id,
                review_id=review_id,
                sequence=sequence,
                quality_status=quality_status,
            )

        response_sha256: str | None = None
        try:
            response_sha256 = self._store_raw_response(session, raw)
        except (ObjectStoreError, OSError, ValueError):
            session.rollback()
            return self._fail(
                session,
                attempt_id,
                worker_id,
                "response_store_unavailable",
                notice_id=notice_id,
                review_id=review_id,
                sequence=sequence,
                quality_status=quality_status,
            )

        try:
            complete_overview_attempt(
                session,
                attempt_id,
                output,
                actor_id=worker_id,
                reason_code="completed",
            )
        except (OverviewResultValidationError, OverviewScopeError) as error:
            # 완료 함수가 이미 ``failed``로 닫았다. 검증 실패를 자동 보정하거나
            # 다시 물어 통과시키지 않는다.
            self._audit(
                session,
                attempt_id,
                status="failed",
                reason_code=error.code,
                notice_id=notice_id,
                review_id=review_id,
                sequence=sequence,
                quality_status=quality_status,
                response_sha256=response_sha256,
            )
            session.commit()
            return OverviewRunResult(
                True, attempt_id, "failed", error.code, expired_leases=len(expired)
            )
        except OverviewAttemptError as error:
            session.rollback()
            return self._fail(
                session,
                attempt_id,
                worker_id,
                error.code,
                notice_id=notice_id,
                review_id=review_id,
                sequence=sequence,
                quality_status=quality_status,
                response_sha256=response_sha256,
            )

        # ── SW사업대상=Y 자동 심층 검토 시작 (명세 §6.4) ─────────────
        # 완료 전이가 이미 성사됐고 commit 전이라 같은 transaction에 있다.
        # 자동 시작은 자기 savepoint session에서 돌므로 실패해도 위의 개요
        # 완료를 되돌리지 않고, 조건이 어긋나면 사람 클릭으로 남는다.
        if notice_id is not None:
            maybe_auto_start_deep_review(
                session, notice_id, service=self._deep_review_service
            )
        self._audit(
            session,
            attempt_id,
            status="completed",
            reason_code=None,
            notice_id=notice_id,
            review_id=review_id,
            sequence=sequence,
            quality_status=quality_status,
            response_sha256=response_sha256,
        )
        session.commit()
        return OverviewRunResult(True, attempt_id, "completed", expired_leases=len(expired))

    # -- 모델 경계 -----------------------------------------------------
    def _invoke(self, client: Any, blocks: list[dict[str, Any]]) -> tuple[Any, bytes]:
        policy = self.policy()
        if policy is None:
            raise OverviewAttemptError("policy_missing")
        try:
            response = client.invoke(policy.stage, {"blocks": blocks}, policy.document)
        except ModelInvocationError:
            raise
        except (ValueError, TypeError) as exc:
            # 경계 있는 prompt 조립이 거부한 입력이다. 잘라서 다시 보내지 않는다.
            raise OverviewAttemptError("prompt_rejected") from exc
        output = getattr(response, "structured_output", None)
        raw = getattr(response, "raw_response", None)
        if not isinstance(output, Mapping):
            raise ModelInvocationError("malformed_json", ())
        if not isinstance(raw, (bytes, bytearray)):
            raise ModelInvocationError("malformed_json", ())
        return output, bytes(raw)

    # -- 원응답 보관 ---------------------------------------------------
    def raw_response_store(self) -> Any:
        if self._raw_response_store is None:
            self._raw_response_store = EncryptedModelResponseStore(
                self.settings or get_settings()
            )
        return self._raw_response_store

    def _store_raw_response(self, session: Session, raw: bytes) -> str:
        """원응답을 암호화 저장소에 쓰고 DB에는 참조·hash만 남긴다."""

        try:
            retention_days = int(os.environ.get("BIDOPS_MODEL_RESPONSE_RETENTION_DAYS", "90"))
        except (TypeError, ValueError):
            retention_days = 90
        retention_days = min(max(retention_days, 1), 90)
        metadata = self.raw_response_store().put_encrypted(
            raw, retention_days=retention_days, content_type="application/json"
        )
        if not isinstance(metadata, Mapping):
            raise ValueError("raw_response_metadata_invalid")
        digest = hashlib.sha256(raw).hexdigest()
        object_key = metadata.get("object_key")
        key_ref = metadata.get("encryption_key_ref")
        if (
            metadata.get("plaintext_sha256") != digest
            or metadata.get("plaintext_size_bytes") != len(raw)
            or not isinstance(object_key, str)
            or not object_key.startswith("model-response/")
            or ".." in object_key.split("/")
            or not isinstance(key_ref, str)
            or not key_ref.strip()
        ):
            raise ValueError("raw_response_metadata_invalid")
        content = session.scalar(
            select(ContentObject).where(ContentObject.sha256 == digest).limit(1)
        )
        if content is None:
            content = ContentObject(
                id=uuid4(),
                sha256=digest,
                size_bytes=len(raw),
                detected_mime="application/json",
                retention_class="model-response-90d",
            )
            session.add(content)
            session.flush()
        elif content.size_bytes != len(raw):
            raise ValueError("raw_response_metadata_invalid")
        existing = session.scalar(
            select(ContentObjectLocation)
            .where(
                ContentObjectLocation.namespace_key == "model-response",
                ContentObjectLocation.object_key == object_key,
            )
            .limit(1)
        )
        if existing is None:
            object_version_id = metadata.get("object_version_id")
            session.add(
                ContentObjectLocation(
                    id=uuid4(),
                    content_object_id=content.id,
                    namespace_key="model-response",
                    object_key=object_key,
                    object_version_id=(
                        object_version_id if isinstance(object_version_id, str) else None
                    ),
                    status="verified",
                    etag=str(metadata.get("etag") or digest),
                    encryption_key_ref=key_ref,
                    verified_at=self.clock(),
                )
            )
        elif existing.content_object_id != content.id:
            raise ValueError("raw_response_metadata_invalid")
        session.flush()
        return digest

    # -- 실패와 감사 ---------------------------------------------------
    def _fail(
        self,
        session: Session,
        attempt_id: UUID,
        worker_id: str,
        reason_code: str,
        *,
        notice_id: int | None,
        review_id: UUID | None,
        sequence: int,
        quality_status: str,
        response_sha256: str | None = None,
    ) -> OverviewRunResult:
        code = (reason_code or "failed")[:64]
        attempt = session.get(PreSpecOverviewAttempt, attempt_id)
        if attempt is not None and attempt.status in {"queued", "running"}:
            fail_overview_attempt(
                session, attempt_id, actor_id=worker_id, reason_code=code
            )
        self._audit(
            session,
            attempt_id,
            status="failed",
            reason_code=code,
            notice_id=notice_id,
            review_id=review_id,
            sequence=sequence,
            quality_status=quality_status,
            response_sha256=response_sha256,
        )
        session.commit()
        return OverviewRunResult(True, attempt_id, "failed", code)

    def _audit(
        self,
        session: Session,
        attempt_id: UUID,
        *,
        status: str,
        reason_code: str | None,
        notice_id: int | None,
        review_id: UUID | None,
        sequence: int,
        quality_status: str,
        response_sha256: str | None = None,
    ) -> None:
        """안정 식별자·상태·분류·hash만 남긴다.

        프롬프트·모델 응답·object key·경로·비밀값은 감사 metadata에 넣지 않는다.
        """

        session.add(
            AuditEvent(
                actor_kind="system",
                claimed_name=None,
                action=OVERVIEW_AUDIT_ACTION,
                aggregate_type="prespec_overview_attempt",
                aggregate_id=str(attempt_id),
                safe_metadata={
                    "notice_id": notice_id,
                    "review_id": str(review_id) if review_id is not None else None,
                    "sequence": sequence,
                    "status": status,
                    "reason_code": reason_code,
                    "quality_status": quality_status,
                    "response_sha256": (
                        response_sha256
                        if isinstance(response_sha256, str)
                        and _SHA256.fullmatch(response_sha256)
                        else None
                    ),
                },
            )
        )


__all__ = [
    "OVERVIEW_AUDIT_ACTION",
    "OVERVIEW_LEASE_SECONDS",
    "OVERVIEW_STAGE",
    "OverviewRunResult",
    "PreSpecOverviewRunner",
]
