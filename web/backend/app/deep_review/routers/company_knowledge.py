"""회사 지식 읽기 REST (데모 계약 §4).

경로 접두사는 lifecycle의 `/api/companies`이지만 제공 모듈은 deep_review다
(명세 §5.3). 세 GET endpoint뿐이며 쓰기·잠금·원본 bytes 읽기·모델 호출이 없다.
`BIDOPS_DEMO_ENABLED=false`이면 조립 계층의 demo guard가 검증보다 먼저 404를 낸다.

**여기서 ORM을 직접 다루지 않는다** (§4의 router 경계). 조회·계보 검증은
`services/company_knowledge`의 함수가 하고, 이 파일은 query를 옮기고 안정 오류
코드를 HTTP 상태로 바꾸는 일만 한다. 응답에는 source locator·object key·경로를
담지 않으며, 예기치 못한 예외는 내용을 남기지 않고 processing_failed로 바꾼다.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ...core.company_ontology import STABLE_KEY_RE
from ...core.db import get_db
from ..schemas.company_knowledge import (
    CompanyKnowledgeGraphView,
    CompanyProfileEvidenceView,
    CompanyProfileView,
)
from ..services.company_knowledge import (
    GRAPH_DEFAULT_DEPTH,
    GRAPH_DEFAULT_LIMIT,
    GRAPH_MAX_DEPTH,
    GRAPH_MAX_LIMIT,
    CompanyKnowledgeServiceError,
    company_knowledge_graph_view,
    company_profile_evidence_view,
    company_profile_view,
)

router = APIRouter(prefix="/api/companies", tags=["company-knowledge"])

_ERRORS: dict[str, tuple[int, str]] = {
    "invalid_request": (422, "요청이 올바르지 않습니다"),
    "not_found": (404, "회사 또는 회사 지식 버전을 찾을 수 없습니다"),
    "company_profile_not_ready": (409, "회사 프로필이 아직 준비되지 않았습니다"),
    "processing_failed": (500, "회사 지식을 처리할 수 없습니다"),
}


def _error(code: str) -> JSONResponse:
    safe = code if code in _ERRORS else "processing_failed"
    status_code, message = _ERRORS[safe]
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {"code": safe, "message": message, "details": None},
            "request_id": None,
        },
    )


def _respond(session: Session, read) -> JSONResponse:  # type: ignore[no-untyped-def]
    try:
        view: BaseModel = read()
        content = view.model_dump(mode="json")
    except CompanyKnowledgeServiceError as error:
        session.rollback()
        return _error(error.code)
    except Exception:  # noqa: BLE001 - safe API boundary, nothing is logged
        session.rollback()
        return _error("processing_failed")
    # Reads never write; end the read transaction without committing.
    session.rollback()
    return JSONResponse(status_code=200, content=content)


@router.get("/{company_id}/profile", response_model=CompanyProfileView)
def company_profile(
    company_id: UUID,
    graph_version_id: UUID | None = Query(default=None),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _respond(
        session,
        lambda: company_profile_view(
            session, company_id=company_id, graph_version_id=graph_version_id
        ),
    )


@router.get("/{company_id}/knowledge-graph", response_model=CompanyKnowledgeGraphView)
def company_knowledge_graph(
    company_id: UUID,
    graph_version_id: UUID | None = Query(default=None),
    root_node_id: str | None = Query(default=None, pattern=STABLE_KEY_RE.pattern),
    depth: int = Query(default=GRAPH_DEFAULT_DEPTH, ge=1, le=GRAPH_MAX_DEPTH),
    limit: int = Query(default=GRAPH_DEFAULT_LIMIT, ge=1, le=GRAPH_MAX_LIMIT),
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _respond(
        session,
        lambda: company_knowledge_graph_view(
            session,
            company_id=company_id,
            graph_version_id=graph_version_id,
            root_node_id=root_node_id,
            depth=depth,
            limit=limit,
        ),
    )


@router.get(
    "/{company_id}/profile-evidence/{evidence_id}",
    response_model=CompanyProfileEvidenceView,
)
def company_profile_evidence(
    company_id: UUID,
    evidence_id: UUID,
    session: Session = Depends(get_db),
) -> JSONResponse:
    return _respond(
        session,
        lambda: company_profile_evidence_view(
            session, company_id=company_id, evidence_id=evidence_id
        ),
    )


__all__ = ["router"]
