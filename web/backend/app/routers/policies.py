"""Immutable screening-policy version REST endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import ScreeningPolicy
from ..schemas import (
    PolicyActivationRequest,
    PolicyActivationResponse,
    PolicyCandidateRequest,
    PolicyVersionCreateRequest,
    PolicyVersionListResponse,
    PolicyVersionResponse,
)
from ..screening.policy import (
    PolicyActivationError,
    PolicyConflict,
    PolicyError,
    PolicyRepository,
)


router = APIRouter(prefix="/api/policies", tags=["policies"])


def _policy_response(row: ScreeningPolicy) -> PolicyVersionResponse:
    return PolicyVersionResponse.model_validate(
        {
            "schema_version": row.schema_version,
            "policy_version": row.policy_version,
            "prompt_version": row.prompt_version,
            "perspective_prompts": row.perspective_prompts_json,
            "counterargument_prompt": row.counterargument_prompt_json,
            "synthesis_prompt": row.synthesis_prompt_json,
            "candidate_selection": row.candidate_selection_json,
            "thresholds": row.thresholds_json,
            "content_digest": row.content_digest,
            "status": row.status,
            "created_at": row.created_at,
            "created_by": row.created_by,
            "activated_at": row.activated_at,
            "activated_by": row.activated_by,
            "quality_gate_result_id": row.quality_gate_result_id,
        }
    )


def _not_found(message: str = "정책 버전을 찾을 수 없습니다.") -> HTTPException:
    return HTTPException(status_code=404, detail=message)


@router.get("", response_model=PolicyVersionListResponse)
def list_policies(
    status_filter: Literal["draft", "activation_candidate", "active"] | None = Query(
        default=None, alias="status"
    ),
    session: Session = Depends(get_db),
) -> PolicyVersionListResponse:
    filters = []
    if status_filter is not None:
        filters.append(ScreeningPolicy.status == status_filter)
    total = int(session.scalar(select(func.count()).select_from(ScreeningPolicy).where(*filters)) or 0)
    rows = session.scalars(
        select(ScreeningPolicy)
        .where(*filters)
        .order_by(ScreeningPolicy.created_at.desc(), ScreeningPolicy.policy_version.desc())
    ).all()
    active = session.scalar(
        select(ScreeningPolicy.policy_version).where(ScreeningPolicy.status == "active")
    )
    return PolicyVersionListResponse(
        items=[_policy_response(row) for row in rows],
        total=total,
        active_policy_version=active,
    )


@router.get("/{policy_version}", response_model=PolicyVersionResponse)
def get_policy(
    policy_version: str,
    session: Session = Depends(get_db),
) -> PolicyVersionResponse:
    row = session.get(ScreeningPolicy, policy_version)
    if row is None:
        raise _not_found()
    return _policy_response(row)


@router.post("", response_model=PolicyVersionResponse, status_code=status.HTTP_201_CREATED)
def create_policy(
    request: PolicyVersionCreateRequest,
    session: Session = Depends(get_db),
) -> PolicyVersionResponse:
    # PolicyRepository intentionally supports idempotent seed/retry calls.  A
    # REST create is different: an existing version is an immutable conflict,
    # even if the submitted body happens to be byte-identical.
    if session.get(ScreeningPolicy, request.policy_version) is not None:
        raise HTTPException(status_code=409, detail="정책 버전이 이미 존재합니다.")
    body = {
        "schema_version": "bidops.screening-policy.v1",
        **request.model_dump(exclude={"created_by"}),
    }
    try:
        row = PolicyRepository(session).create(body, created_by=request.created_by)
        session.commit()
    except PolicyConflict as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="정책 버전을 생성할 수 없습니다.") from exc
    except (PolicyError, ValueError) as exc:
        session.rollback()
        raise HTTPException(status_code=422, detail="정책 본문이 계약에 맞지 않습니다.") from exc
    return _policy_response(row)


@router.post("/{policy_version}/candidate", response_model=PolicyVersionResponse)
def designate_candidate(
    policy_version: str,
    request: PolicyCandidateRequest,
    session: Session = Depends(get_db),
) -> PolicyVersionResponse:
    if session.get(ScreeningPolicy, policy_version) is None:
        raise _not_found()
    try:
        row = PolicyRepository(session).designate_candidate(
            policy_version, confirmed_by=request.confirmed_by
        )
        session.commit()
    except PolicyConflict as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="draft 정책만 활성화 후보가 될 수 있습니다.") from exc
    return _policy_response(row)


@router.post("/{policy_version}/activate", response_model=PolicyActivationResponse)
def activate_policy(
    policy_version: str,
    request: PolicyActivationRequest,
    session: Session = Depends(get_db),
) -> PolicyActivationResponse:
    target = session.get(ScreeningPolicy, policy_version)
    if target is None:
        raise _not_found()
    previous = session.scalar(
        select(ScreeningPolicy.policy_version).where(
            ScreeningPolicy.status == "active",
            ScreeningPolicy.policy_version != policy_version,
        )
    )
    try:
        row = PolicyRepository(session).activate(
            policy_version,
            quality_gate_result_id=request.quality_gate_result_id,
            confirmed_by=request.confirmed_by,
        )
        session.commit()
    except (PolicyActivationError, PolicyConflict) as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="운영 품질 게이트가 정책을 승인하지 않았습니다.") from exc
    return PolicyActivationResponse(
        policy=_policy_response(row),
        previous_active_policy_version=previous,
        quality_gate_result_id=request.quality_gate_result_id,
        activation_status="activated",
        activated_at=row.activated_at,
    )


__all__ = ["router"]
