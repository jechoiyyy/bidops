"""Liveness endpoint.

`/api/health`는 어느 도메인 모듈에도 속하지 않으므로 core가 제공한다. 조립
계층은 `BIDOPS_MODULES`가 무엇이든 이 router를 항상 등록한다(명세 §7).
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Return a lightweight liveness response."""

    return {"status": "ok"}
