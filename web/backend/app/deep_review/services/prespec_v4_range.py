"""사람이 개요 입력 범위를 확정하는 경계와, 명시 CLI로만 도는 모델 보조 제안.

결정적 heading 선택기(`select_v4_input_range`)가 경계를 정하지 못하면 준비는
`needs_human_review` target을 동결한다(ADR-RDP-004, Requirements F9). 이 모듈은
그 다음 두 가지만 한다.

1. **사람 확정**: 최신 `needs_human_review` target에 대해 사람이 고른 절 index
   쌍 또는 쪽 쌍을 받아 전체 쪽 텍스트로 새 `ready`·`human_confirmed` target을
   동결한다. attempt·정책 활성화·모델 호출은 하지 않는다 — 자동 실행을 열지
   않는다는 것이 이 단계의 요점이다.
2. **모델 보조 제안**: 참조 실행 모드에서 CLI가 명시적으로 부를 때만 절 후보의
   `index·title·page·char_count`를 보내고, 답을 감사 행 하나로만 남긴다. target도
   attempt도 만들지 않는다.

어느 경로도 rhwp `untrustedContent`(원문 발췌)를 읽지 않는다. 절 제목은 산출물
⑦에 이미 공백 정규화·길이 제한된 값이며 화면 응답과 프롬프트에만 실리고 로그·
감사 metadata에는 넣지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.config import get_settings
from ...core.model_client import (
    ModelClient,
    ModelEndpointError,
    ModelIdentityError,
    ModelInvocationError,
    ResponseTooLargeError,
    StructuredOutputContract,
    resolve_model_endpoint,
    sanitize_for_prompt,
    strip_leading_thinking,
)
from ...core.models import AuditEvent
from ...core.object_store import ObjectStore, ObjectStoreError
from ...lifecycle import lock_notice
from ..models import (
    ContentObject,
    ContentObjectLocation,
    PrespecV4PdfSnapshot,
    PrespecV4Target,
)
from ..schemas.page_overview import (
    PageOverviewRangeAssist,
    PageOverviewRangeCandidate,
    PageOverviewRangeConfirmation,
    PageOverviewRangeReview,
)
from .prespec_v4 import (
    MAX_V4_MANIFEST_BYTES,
    V4PreparationError,
    _persist_artifact,
    _read_verified_artifact,
    freeze_v4_target,
    read_snapshot_section_candidates,
    select_v4_page_span,
)
from .prespec_v4_ops import V4OpsError, _policy_for


RANGE_CONFIRMED_ACTION = "prespec_v4.range_confirmed"
RANGE_ASSIST_ACTION = "prespec_v4.range_assist"
RANGE_TARGET_AGGREGATE = "prespec_v4_target"
MAX_RANGE_NOTE_CHARS = 500
#: 보조 제안 프롬프트에 실을 후보 수 상한. 한 문서의 절 수는 ⑦에서 2,000개까지
#: 유효하지만 프롬프트는 그만큼 키우지 않는다.
MAX_ASSIST_CANDIDATES = 200
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")

#: 범위 보조의 출력 계약. core는 도메인 계약을 모르므로 여기서 넘긴다(ADR-0050).
RANGE_ASSIST_CONTRACT = StructuredOutputContract(
    name="bidops_prespec_v4_range_assist",
    schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["start_index", "end_index", "reason"],
        "properties": {
            "start_index": {"type": "integer"},
            "end_index": {"type": "integer"},
            "reason": {"type": "string"},
        },
    },
    system_prompt=(
        "당신은 제안요청서의 절 목록만 보고 사업 개요·목적·범위에 해당하는 연속 구간을 "
        "고르는 보조자다. 주어진 절 index 범위 밖을 고르지 말고, 근거가 없으면 추정하지 "
        "말고 가장 가까운 개요 절 하나만 고른다. JSON 객체 하나로만 답한다."
    ),
)
_ASSIST_INSTRUCTION = (
    "사업 개요·목적·범위에 해당하는 연속 절 구간의 시작/끝 index를 "
    'JSON {"start_index","end_index","reason"}로만 답하라'
)


@dataclass(frozen=True)
class V4RangeConfirmation:
    """사람이 확정한 범위 하나의 결과(새 target)."""

    target_id: UUID
    selection_status: str
    first_page: int
    last_page: int
    page_numbers: tuple[int, ...]


@dataclass(frozen=True)
class V4RangeAssist:
    """모델 보조 제안 한 번의 결과. target·attempt는 만들지 않는다."""

    target_id: UUID
    status: str
    start_index: int | None
    end_index: int | None
    reason_code: str | None
    model_name: str
    model_revision: str
    prompt_sha256: str
    response_sha256: str | None
    quality_status: str


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


def _safe_reason(value: Any, default: str) -> str:
    code = str(value or "")
    return code if _SAFE_CODE.fullmatch(code) else default


def _latest_target(session: Session, notice_id: int) -> PrespecV4Target | None:
    return session.scalar(
        select(PrespecV4Target)
        .where(PrespecV4Target.notice_id == notice_id)
        .order_by(PrespecV4Target.created_at.desc(), PrespecV4Target.id.desc())
        .limit(1)
    )


def _pending_target(session: Session, target: PrespecV4Target) -> None:
    """최신 target이 아니거나 확정 대기 상태가 아니면 닫는다."""

    latest = _latest_target(session, target.notice_id)
    if latest is None or latest.id != target.id or target.selection_status != "needs_human_review":
        raise V4OpsError("target_not_pending")


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise V4OpsError("range_invalid")
    return value


def _candidates(session: Session, store: ObjectStore, snapshot: PrespecV4PdfSnapshot) -> dict[str, Any] | None:
    try:
        return read_snapshot_section_candidates(session, store, snapshot)
    except V4PreparationError as error:
        raise V4OpsError(error.code) from error


def _page_text_payload(
    session: Session,
    store: ObjectStore,
    snapshot: PrespecV4PdfSnapshot,
) -> Mapping[str, Any]:
    """준비 경계와 **같은 방식**으로 고정된 page-text 산출물을 다시 읽는다."""

    content = session.get(ContentObject, snapshot.page_text_content_object_id)
    location = session.get(ContentObjectLocation, snapshot.page_text_location_id)
    if content is None or location is None:
        raise V4OpsError("page_text_unavailable")
    try:
        raw = _read_verified_artifact(
            store, location, content, max_bytes=min(content.size_bytes, MAX_V4_MANIFEST_BYTES)
        )
        payload = json.loads(raw)
    except V4PreparationError as error:
        raise V4OpsError(error.code) from error
    except (ObjectStoreError, ValueError, UnicodeError) as error:
        raise V4OpsError("page_text_invalid") from error
    if not isinstance(payload, Mapping):
        raise V4OpsError("page_text_invalid")
    return payload


def _pages_from_indices(
    candidates: Mapping[str, Any] | None,
    start_index: int,
    end_index: int,
    pdf_page_count: int,
) -> tuple[int, int]:
    """후보 index 쌍을 연속 쪽 범위로 바꾼다 (R7 고정 규칙).

    시작은 고른 절의 쪽, 끝은 **다음 절의 쪽**(마지막 절이면 문서 끝 쪽)이다.
    다음 절이 같은 쪽에서 시작하면 한 쪽짜리 범위가 된다.
    """

    sections = list(candidates.get("sections") or []) if candidates else []
    if not sections:
        raise V4OpsError("range_invalid")
    if start_index < 0 or end_index < start_index or end_index >= len(sections):
        raise V4OpsError("range_invalid")
    first_page = int(sections[start_index]["page"])
    last_page = (
        int(sections[end_index + 1]["page"]) if end_index + 1 < len(sections) else int(pdf_page_count)
    )
    if last_page < first_page:
        last_page = first_page
    return first_page, last_page


def confirm_v4_range(
    session: Session,
    store: ObjectStore,
    *,
    notice_id: int,
    target_id: UUID,
    actor: str,
    start_index: int | None = None,
    end_index: int | None = None,
    first_page: int | None = None,
    last_page: int | None = None,
    note: str | None = None,
) -> V4RangeConfirmation:
    """사람이 고른 범위로 새 `ready`·`human_confirmed` target을 동결한다.

    commit은 하지 않는다(router가 한 트랜잭션으로 묶는다). attempt를 만들지
    않으며 정책·모델을 건드리지 않는다 — 확정은 입력을 준비할 뿐이고 실행은
    별도 승인이다.
    """

    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise V4OpsError("actor_required")
    actor = actor.strip()
    if note is not None and (not isinstance(note, str) or len(note) > MAX_RANGE_NOTE_CHARS):
        raise V4OpsError("range_invalid")
    start_index = _int_or_none(start_index)
    end_index = _int_or_none(end_index)
    first_page = _int_or_none(first_page)
    last_page = _int_or_none(last_page)
    by_index = start_index is not None and end_index is not None
    by_page = first_page is not None and last_page is not None
    # 정확히 한 쌍만 허용한다. 둘을 함께 받으면 무엇이 정본인지 알 수 없다.
    if by_index == by_page or (start_index is None) != (end_index is None) or (first_page is None) != (last_page is None):
        raise V4OpsError("range_invalid")

    # 공고 잠금이 "최신 target" 판정의 fence다. 없으면 동시 요청 둘이 같은 확정
    # 대기 target에서 각자 ready target을 동결할 수 있다.
    if lock_notice(session, notice_id) is None:
        raise V4OpsError("target_not_found")
    target = session.get(PrespecV4Target, target_id)
    if target is None or target.notice_id != notice_id:
        raise V4OpsError("target_not_found")
    _pending_target(session, target)
    snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id)
    if snapshot is None:
        raise V4OpsError("snapshot_not_found")

    candidates = _candidates(session, store, snapshot)
    candidate_count = int(candidates["section_count"]) if candidates else 0
    if by_index:
        first_page, last_page = _pages_from_indices(candidates, start_index, end_index, snapshot.pdf_page_count)
    if first_page < 1 or last_page < first_page or last_page > snapshot.pdf_page_count:
        raise V4OpsError("range_invalid")

    payload = _page_text_payload(session, store, snapshot)
    locator_kind = "section_candidate" if by_index else "page"
    start_locator: dict[str, Any] = {"kind": locator_kind, "page": first_page}
    end_locator: dict[str, Any] = {"kind": locator_kind, "page": last_page}
    if by_index:
        start_locator["candidate_index"] = start_index
        end_locator["candidate_index"] = end_index
    try:
        selection = select_v4_page_span(
            {
                "document_version_id": str(snapshot.document_version_id),
                "source_sha256": snapshot.source_sha256,
                "pages": payload.get("pages"),
                "blocks": payload.get("blocks", []),
            },
            first_page,
            last_page,
            start_locator=start_locator,
            end_locator=end_locator,
            extra={
                "confirmed_from_target_id": str(target.id),
                "confirmed_by": actor,
                "note": note if note else None,
                "candidate_indices": {"start": start_index, "end": end_index} if by_index else None,
            },
        )
        manifest_content, manifest_location = _persist_artifact(
            session,
            store,
            namespace="structure",
            object_key=(
                f"structure/prespec-v4/{snapshot.document_version_id}/"
                f"manifest-{_sha256(selection.manifest_bytes)}.json"
            ),
            data=selection.manifest_bytes,
            detected_mime="application/json",
            retention_class="prespec-v4-input",
        )
        confirmed = freeze_v4_target(
            session,
            snapshot_id=snapshot.id,
            observation_kind=target.observation_kind,
            observation_id=target.observation_id,
            observation_reference=target.observation_jsonb,
            selection=selection,
            manifest_content_object_id=manifest_content.id,
            manifest_location_id=manifest_location.id,
            manifest_bytes=selection.manifest_bytes,
        )
    except V4PreparationError as error:
        if error.code == "input_size_limit":
            raise V4OpsError("input_size_limit") from error
        if error.code in {"page_range_invalid", "range_confirmation_invalid"}:
            raise V4OpsError("range_invalid") from error
        raise V4OpsError(error.code) from error
    except ObjectStoreError as error:
        raise V4OpsError("manifest_storage_failed") from error

    session.add(AuditEvent(
        actor_kind="human",
        claimed_name=actor,
        action=RANGE_CONFIRMED_ACTION,
        aggregate_type=RANGE_TARGET_AGGREGATE,
        aggregate_id=str(confirmed.id),
        # 원문·절 제목은 넣지 않는다. 무엇을 골랐는지의 좌표만 남긴다.
        safe_metadata={
            "from_target_id": str(target.id),
            "start_index": start_index,
            "end_index": end_index,
            "first_page": first_page,
            "last_page": last_page,
            "candidate_count": candidate_count,
        },
        created_at=_now(),
    ))
    session.flush()
    return V4RangeConfirmation(
        target_id=confirmed.id,
        selection_status=confirmed.selection_status,
        first_page=first_page,
        last_page=last_page,
        page_numbers=tuple(range(first_page, last_page + 1)),
    )


def _latest_assist(session: Session, target_id: UUID) -> AuditEvent | None:
    return session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.action == RANGE_ASSIST_ACTION,
            AuditEvent.aggregate_type == RANGE_TARGET_AGGREGATE,
            AuditEvent.aggregate_id == str(target_id),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )


def _assist_projection(session: Session, target_id: UUID) -> PageOverviewRangeAssist | None:
    """제안이 남아 있으면 그 좌표만 투영한다. 모델이 적은 사유 문장은 계약에 없다."""

    event = _latest_assist(session, target_id)
    metadata = event.safe_metadata if event is not None else None
    if not isinstance(metadata, Mapping) or metadata.get("status") != "suggested":
        return None
    start = metadata.get("start_index")
    end = metadata.get("end_index")
    quality = metadata.get("quality_status")
    if (
        isinstance(start, bool) or isinstance(end, bool)
        or not isinstance(start, int) or not isinstance(end, int)
        or quality not in {"unmeasured_reference", "mock_reference"}
        or not isinstance(metadata.get("model_name"), str)
    ):
        return None
    return PageOverviewRangeAssist(
        start_index=start, end_index=end, model_name=str(metadata["model_name"]),
        quality_status=quality, created_at=event.created_at,
    )


def _confirmation_projection(
    session: Session,
    store: ObjectStore,
    target: PrespecV4Target,
) -> PageOverviewRangeConfirmation:
    """확정 target의 불변 manifest와 감사 행에서 확정 사실만 읽는다."""

    content = session.get(ContentObject, target.manifest_content_object_id)
    location = session.get(ContentObjectLocation, target.manifest_location_id)
    if content is None or location is None:
        raise V4OpsError("manifest_unavailable")
    try:
        raw = _read_verified_artifact(
            store, location, content, max_bytes=min(content.size_bytes, MAX_V4_MANIFEST_BYTES)
        )
        manifest = json.loads(raw)
    except V4PreparationError as error:
        raise V4OpsError(error.code) from error
    except (ObjectStoreError, ValueError, UnicodeError) as error:
        raise V4OpsError("manifest_invalid") from error
    pages = manifest.get("pages") if isinstance(manifest, Mapping) else None
    origin = manifest.get("confirmed_from_target_id") if isinstance(manifest, Mapping) else None
    if not isinstance(pages, list) or not pages or not isinstance(origin, str):
        raise V4OpsError("manifest_invalid")
    numbers = [int(page["number"]) for page in pages if isinstance(page, Mapping)]
    if len(numbers) != len(pages) or numbers != list(range(numbers[0], numbers[-1] + 1)):
        raise V4OpsError("manifest_invalid")
    indices = manifest.get("candidate_indices")
    start = indices.get("start") if isinstance(indices, Mapping) else None
    end = indices.get("end") if isinstance(indices, Mapping) else None
    event = session.scalar(
        select(AuditEvent)
        .where(
            AuditEvent.action == RANGE_CONFIRMED_ACTION,
            AuditEvent.aggregate_type == RANGE_TARGET_AGGREGATE,
            AuditEvent.aggregate_id == str(target.id),
        )
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(1)
    )
    note = manifest.get("note")
    return PageOverviewRangeConfirmation(
        target_id=target.id,
        confirmed_from_target_id=UUID(origin),
        start_index=start if isinstance(start, int) and not isinstance(start, bool) else None,
        end_index=end if isinstance(end, int) and not isinstance(end, bool) else None,
        first_page=numbers[0],
        last_page=numbers[-1],
        page_numbers=numbers,
        actor=str(manifest.get("confirmed_by") or (event.claimed_name if event is not None else "") or "unknown"),
        note=note if isinstance(note, str) and note else None,
        created_at=event.created_at if event is not None else target.created_at,
    )


def range_review_projection(
    session: Session,
    notice_id: int,
    *,
    store_factory: Callable[[], ObjectStore],
) -> PageOverviewRangeReview | None:
    """`GET /api/pre-specs/{id}/overview-pages`의 `range_review`를 만든다.

    규칙은 **최신 target 하나**다. 최신이 `needs_human_review`면 확정 대기,
    사람이 확정한 `ready`면 확정 상태, 그 밖(heading_scope ready 등)에는 이 자리
    자체가 없다(`None`). 저장·모델 호출은 없다. 후보·manifest 읽기가 실패하면
    조용히 빈 값으로 낮추지 않고 올린다(fail closed).
    """

    target = _latest_target(session, notice_id)
    if target is None:
        return None
    confirmed = target.selection_status == "ready" and target.selection_strategy == "human_confirmed"
    if target.selection_status != "needs_human_review" and not confirmed:
        return None
    snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id)
    if snapshot is None:
        raise V4OpsError("snapshot_not_found")
    store = store_factory()
    candidates = _candidates(session, store, snapshot)
    sections = list(candidates.get("sections") or []) if candidates else []
    confirmation = _confirmation_projection(session, store, target) if confirmed else None
    # 제안은 선택기가 동결한 target에 달린다. 확정 뒤에도 그 target의 기록을 읽는다.
    assist_target = confirmation.confirmed_from_target_id if confirmation is not None else target.id
    return PageOverviewRangeReview(
        target_id=target.id,
        snapshot_id=snapshot.id,
        selection_status=target.selection_status,
        reason_code=target.reason_code,
        pdf_page_count=snapshot.pdf_page_count,
        created_at=target.created_at,
        candidates_mode=str(candidates["mode"]) if candidates and sections else None,
        candidates=[
            PageOverviewRangeCandidate(
                index=int(item["index"]), title=str(item["title"]),
                page=int(item["page"]), char_count=int(item["char_count"]),
            )
            for item in sections
        ],
        assisted=_assist_projection(session, assist_target),
        confirmation=confirmation,
    )


def _assist_prompt(candidates: Mapping[str, Any]) -> str:
    """후보의 좌표·제목만 담은 bounded 프롬프트. 경로·자격증명은 실리지 않는다."""

    sections = [
        {
            "index": int(item["index"]), "title": str(item["title"]),
            "page": int(item["page"]), "char_count": int(item["char_count"]),
        }
        for item in list(candidates.get("sections") or [])[:MAX_ASSIST_CANDIDATES]
    ]
    payload = sanitize_for_prompt({
        "instruction": _ASSIST_INSTRUCTION,
        "page_count": int(candidates["page_count"]),
        "sections_mode": str(candidates["mode"]),
        "sections": sections,
    })
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _assist_answer(payload: Mapping[str, Any], count: int) -> tuple[int, int, bytes]:
    """응답 원형에서 index 쌍만 꺼내고 범위를 검증한다."""

    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], Mapping):
        raise ValueError("assist_response_invalid")
    choice = choices[0]
    message = choice.get("message")
    if choice.get("finish_reason") != "stop" or not isinstance(message, Mapping):
        raise ValueError("assist_response_invalid")
    content = message.get("content")
    if not isinstance(content, str):
        raise ValueError("assist_response_invalid")
    raw = content.encode("utf-8")
    parsed, _thinking = strip_leading_thinking(content)
    value = json.loads(parsed)
    if not isinstance(value, Mapping):
        raise ValueError("assist_response_invalid")
    start = value.get("start_index")
    end = value.get("end_index")
    if (
        isinstance(start, bool) or isinstance(end, bool)
        or not isinstance(start, int) or not isinstance(end, int)
        or not isinstance(value.get("reason"), str)
    ):
        raise ValueError("assist_response_invalid")
    if start < 0 or end < start or end >= count:
        raise ValueError("assist_index_out_of_range")
    return start, end, raw


def assist_v4_range(
    session: Session,
    store: ObjectStore,
    *,
    target_id: UUID,
    actor: str,
    settings: Any | None = None,
    client: Any | None = None,
) -> V4RangeAssist:
    """절 후보로 범위를 **제안**하고 감사 행 하나만 남긴다 (CLI 전용).

    참조 실행 모드에서만 돌고, 최신·확정 대기·후보 2개 이상인 target 한 건에
    대해 한 번만 실행된다. target·attempt를 만들지 않으므로 이 결과로 개요 검토가
    열리지 않는다. 원응답 본문은 저장하지 않고 hash만 남긴다 — 감사 행은 참조할
    소유 행이 없어 암호화 model-response 객체를 고아로 남기게 된다.
    """

    if not isinstance(actor, str) or not actor.strip() or len(actor) > 128:
        raise V4OpsError("actor_required")
    actor = actor.strip()
    settings = settings or get_settings()
    if not getattr(settings, "reference_workflow_mode", False):
        raise V4OpsError("reference_workflow_disabled")
    target = session.get(PrespecV4Target, target_id)
    if target is None:
        raise V4OpsError("target_not_found")
    _pending_target(session, target)
    snapshot = session.get(PrespecV4PdfSnapshot, target.snapshot_id)
    if snapshot is None:
        raise V4OpsError("snapshot_not_found")
    candidates = _candidates(session, store, snapshot)
    sections = list(candidates.get("sections") or []) if candidates else []
    if len(sections) < 2:
        raise V4OpsError("assist_not_applicable")
    previous = _latest_assist(session, target.id)
    if previous is not None and isinstance(previous.safe_metadata, Mapping) and previous.safe_metadata.get("status") in {"suggested", "invalid"}:
        raise V4OpsError("assist_already_recorded")

    # 호출 전에 용도별 설정을 푼다. 허용 host가 비었거나 선언 revision이 64자
    # hex가 아니면 여기서 멈춘다(ADR-0050).
    try:
        endpoint = resolve_model_endpoint("overview", settings=settings)
    except (ModelEndpointError, ModelIdentityError, ValueError, OSError) as error:
        raise V4OpsError("model_binding_unavailable") from error
    model_name = _policy_for(settings).model_name
    quality_status = "mock_reference" if getattr(settings, "analysis_provider", "vllm") == "mock" else "unmeasured_reference"
    prompt = _assist_prompt(candidates)
    prompt_sha256 = _sha256(prompt.encode("utf-8"))

    status, reason_code = "suggested", None
    start_index: int | None = None
    end_index: int | None = None
    raw: bytes | None = None
    owned: ModelClient | None = None
    try:
        if client is None:
            owned = ModelClient.for_purpose(
                "overview", model=model_name, output_contract=RANGE_ASSIST_CONTRACT, settings=settings
            )
            client = owned
        # 재시도는 하지 않는다. `complete_structured`는 한 번만 요청한다.
        response = client.complete_structured(prompt, contract=RANGE_ASSIST_CONTRACT)
        if not isinstance(response, Mapping):
            raise ValueError("assist_response_invalid")
        start_index, end_index, raw = _assist_answer(response, len(sections))
    # transport·identity·예산 실패는 "호출 실패"이고, 계약을 지키지 않은 응답은
    # "무효"다. 둘을 섞으면 감사 행이 무엇이 일어났는지 말하지 못한다.
    except (ModelEndpointError, ModelIdentityError, ModelInvocationError, ResponseTooLargeError) as error:
        status, reason_code = "failed", _safe_reason(getattr(error, "code", None), "assist_call_failed")
        start_index = end_index = None
    except (ValueError, TypeError) as error:
        status, reason_code = "invalid", _safe_reason(getattr(error, "code", None) or str(error), "assist_response_invalid")
        start_index = end_index = None
    except Exception as error:  # provider transport 예외(openai·httpx)까지 감사로 닫는다
        status, reason_code = "failed", _safe_reason(getattr(error, "code", None), "assist_call_failed")
        start_index = end_index = None
    finally:
        if owned is not None:
            owned.close()

    session.add(AuditEvent(
        actor_kind="human",
        claimed_name=actor,
        action=RANGE_ASSIST_ACTION,
        aggregate_type=RANGE_TARGET_AGGREGATE,
        aggregate_id=str(target.id),
        # 절 제목·모델 사유 문장은 남기지 않는다. 좌표와 hash만 남긴다.
        safe_metadata={
            "status": status,
            "start_index": start_index,
            "end_index": end_index,
            "model_name": model_name,
            "model_revision": endpoint.model_revision,
            "prompt_sha256": prompt_sha256,
            "response_sha256": _sha256(raw) if raw is not None else None,
            "quality_status": quality_status,
            "reason_code": reason_code,
        },
        created_at=_now(),
    ))
    session.flush()
    return V4RangeAssist(
        target_id=target.id, status=status, start_index=start_index, end_index=end_index,
        reason_code=reason_code, model_name=model_name, model_revision=endpoint.model_revision,
        prompt_sha256=prompt_sha256, response_sha256=_sha256(raw) if raw is not None else None,
        quality_status=quality_status,
    )


__all__ = [
    "MAX_RANGE_NOTE_CHARS",
    "RANGE_ASSIST_ACTION",
    "RANGE_ASSIST_CONTRACT",
    "RANGE_CONFIRMED_ACTION",
    "V4RangeAssist",
    "V4RangeConfirmation",
    "assist_v4_range",
    "confirm_v4_range",
    "range_review_projection",
]
