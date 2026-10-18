"""RL-04 제안서 초안 REST 8개 (spec "REST (`bidops.proposal.v1`)").

| 호출 | 성공 |
|---|---|
| `GET /api/opportunities/{id}/proposal?draft_id=` | 200 `ProposalView` (초안 없으면 `{draft:null}`) |
| `POST /api/opportunities/{id}/proposal-requests` | 202 `{draft_id, status}` |
| `POST /api/proposals/{draft_id}/sections/{key}/regenerations` | 202 `{section_id, revision}` |
| `PATCH /api/proposals/{draft_id}/sections/{key}/review` | 200 `SectionView` |
| `POST /api/proposals/{draft_id}/sentences/{sentence_id}/edits` | 201 `{edit_id}` |
| `POST /api/proposals/{draft_id}/exports` | 201 `{export_id, pdf_sha256, created}` |
| `GET /api/proposals/{draft_id}/exports/{export_id}.pdf` | 200 `application/pdf` |
| `PATCH /api/proposals/{draft_id}/stage` | 200 `{stage}` |

`/api/opportunities` 접두사는 lifecycle 것이지만 제공 모듈은 deep_review다.
`BIDOPS_RL_ANALYSIS_ENABLED=false`이면 조립 계층 미들웨어가 먼저 404를 내고 service도 같은
판정(실회사·RL 켜짐)을 한 번 더 한다. 사람 mutation은 `X-BidOps-Actor-Name`(+`-Format`)이
필요하다. 본문 검증 실패는 FastAPI 기본 422, 그 밖의 안정 오류는 공통 `error` envelope다.
이 파일은 본문 검증과 오류 코드 → HTTP 변환만 하고 상태 전이·저장은 service가 한다.
"""

from __future__ import annotations

from typing import Annotated, Any, Callable
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path as ApiPath, Query
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from ...core.api_errors import BundleServiceError, validate_actor
from ...core.db import get_db
from ..schemas.proposal import (
    DraftStageUpdate,
    DraftStageView,
    ProposalExportCreate,
    ProposalExportReceipt,
    ProposalRequestCreate,
    ProposalRequestReceipt,
    ProposalView,
    SectionRegenerationCreate,
    SectionRegenerationReceipt,
    SectionReviewUpdate,
    SectionView,
    SentenceEditCreate,
    SentenceEditReceipt,
)
from ..services.proposal_draft import (
    ERROR_MESSAGES,
    ERROR_STATUS,
    ProposalServiceError,
    create_proposal_draft,
    request_section_regeneration,
)
from ..services.proposal_view import (
    create_export,
    create_sentence_edit,
    export_pdf,
    proposal_view,
    require_proposal_path,
    review_section,
    set_draft_stage,
)


router = APIRouter(tags=["proposals"])

ActorHeader = Annotated[str | None, Header(alias="X-BidOps-Actor-Name")]
ActorFormatHeader = Annotated[str | None, Header(alias="X-BidOps-Actor-Name-Format")]


def _error_response(code: str, *, request_id: UUID | None = None) -> JSONResponse:
    safe = code if code in ERROR_STATUS else "processing_failed"
    return JSONResponse(
        status_code=ERROR_STATUS[safe],
        content={
            "error": {"code": safe, "message": ERROR_MESSAGES[safe], "details": None},
            "request_id": str(request_id) if request_id else None,
        },
    )


def _actor(actor: str | None, actor_format: str | None) -> str:
    claimed = validate_actor(actor, actor_format)
    if claimed.casefold().startswith("system:"):
        raise BundleServiceError("actor_name_invalid", "담당자 이름이 올바르지 않습니다", status_code=400)
    return claimed


def _run(session: Session, call: Callable[[], Any], *, status: int, request_id: UUID | None = None) -> Response:
    try:
        content = call()
    except (ProposalServiceError, BundleServiceError) as error:
        session.rollback()
        return _error_response(error.code, request_id=request_id)
    except Exception:  # noqa: BLE001 - safe API boundary; nothing about the data is logged
        session.rollback()
        return _error_response("processing_failed", request_id=request_id)
    if isinstance(content, Response):
        return content
    if session.in_transaction():
        session.rollback()
    return JSONResponse(status_code=status, content=content)


@router.get("/api/opportunities/{opportunity_id}/proposal", response_model=ProposalView)
def get_opportunity_proposal(
    opportunity_id: int = ApiPath(..., ge=1),
    draft_id: UUID | None = Query(default=None),
    session: Session = Depends(get_db),
) -> Response:
    return _run(session, lambda: proposal_view(session, opportunity_id=opportunity_id, draft_id=draft_id), status=200)


@router.post("/api/opportunities/{opportunity_id}/proposal-requests", response_model=ProposalRequestReceipt,
             status_code=202)
def create_opportunity_proposal_request(
    payload: ProposalRequestCreate,
    opportunity_id: int = ApiPath(..., ge=1),
    actor: ActorHeader = None,
    actor_format: ActorFormatHeader = None,
    session: Session = Depends(get_db),
) -> Response:
    def call() -> dict[str, Any]:
        claimed = _actor(actor, actor_format)
        require_proposal_path(session)
        result = create_proposal_draft(session, opportunity_id=opportunity_id, actor=claimed,
                                       request_id=payload.request_id)
        return {"draft_id": result["draft_id"], "status": result["status"]}

    return _run(session, call, status=202, request_id=payload.request_id)


@router.post("/api/proposals/{draft_id}/sections/{section_key}/regenerations",
             response_model=SectionRegenerationReceipt, status_code=202)
def create_section_regeneration(
    payload: SectionRegenerationCreate,
    draft_id: UUID,
    section_key: str,
    actor: ActorHeader = None,
    actor_format: ActorFormatHeader = None,
    session: Session = Depends(get_db),
) -> Response:
    def call() -> dict[str, Any]:
        claimed = _actor(actor, actor_format)
        require_proposal_path(session)
        result = request_section_regeneration(session, draft_id=draft_id, section_key=section_key, actor=claimed,
                                              request_id=payload.request_id)
        return {"section_id": result["section_id"], "revision": result["revision"]}

    return _run(session, call, status=202, request_id=payload.request_id)


@router.patch("/api/proposals/{draft_id}/sections/{section_key}/review", response_model=SectionView)
def patch_section_review(
    payload: SectionReviewUpdate,
    draft_id: UUID,
    section_key: str,
    actor: ActorHeader = None,
    actor_format: ActorFormatHeader = None,
    session: Session = Depends(get_db),
) -> Response:
    return _run(session, lambda: review_section(
        session, draft_id=draft_id, section_key=section_key, actor=_actor(actor, actor_format),
        request_id=payload.request_id,
    ), status=200, request_id=payload.request_id)


@router.post("/api/proposals/{draft_id}/sentences/{sentence_id}/edits", response_model=SentenceEditReceipt,
             status_code=201)
def create_proposal_sentence_edit(
    payload: SentenceEditCreate,
    draft_id: UUID,
    sentence_id: UUID,
    actor: ActorHeader = None,
    actor_format: ActorFormatHeader = None,
    session: Session = Depends(get_db),
) -> Response:
    return _run(session, lambda: create_sentence_edit(
        session, draft_id=draft_id, sentence_id=sentence_id, text=payload.text,
        actor=_actor(actor, actor_format), request_id=payload.request_id,
    ), status=201, request_id=payload.request_id)


@router.post("/api/proposals/{draft_id}/exports", response_model=ProposalExportReceipt, status_code=201)
def create_proposal_export(
    payload: ProposalExportCreate,
    draft_id: UUID,
    actor: ActorHeader = None,
    actor_format: ActorFormatHeader = None,
    session: Session = Depends(get_db),
) -> Response:
    return _run(session, lambda: create_export(
        session, draft_id=draft_id, actor=_actor(actor, actor_format), request_id=payload.request_id,
    ), status=201, request_id=payload.request_id)


@router.get("/api/proposals/{draft_id}/exports/{export_id}.pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def get_proposal_export_pdf(
    draft_id: UUID,
    export_id: UUID,
    session: Session = Depends(get_db),
) -> Response:
    def call() -> Response:
        data, sha = export_pdf(session, draft_id=draft_id, export_id=export_id)
        session.rollback()
        return Response(content=data, media_type="application/pdf", headers={"X-BidOps-Export-Sha256": sha})

    return _run(session, call, status=200)


@router.patch("/api/proposals/{draft_id}/stage", response_model=DraftStageView)
def patch_draft_stage(
    payload: DraftStageUpdate,
    draft_id: UUID,
    actor: ActorHeader = None,
    actor_format: ActorFormatHeader = None,
    session: Session = Depends(get_db),
) -> Response:
    return _run(session, lambda: set_draft_stage(
        session, draft_id=draft_id, stage=payload.stage, actor=_actor(actor, actor_format),
        request_id=payload.request_id,
    ), status=200, request_id=payload.request_id)


__all__ = ["router"]
