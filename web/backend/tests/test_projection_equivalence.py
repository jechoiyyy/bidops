"""판정 projection 전환 전후의 REST 응답 동일성 (명세 §6.1).

`GET /api/notices`·`/{pk}`·`/related`·`/history`·`/api/runs/{id}/stats`·
`/api/metrics/validation`·`/api/reviews*`가 screening의 projection을 거치도록
바뀌어도 응답이 바이트 단위로 같아야 한다. 이 파일의 golden은 전환 **전** 코드로
한 번 만들었고(`BIDOPS_WRITE_PROJECTION_GOLDEN=1`), 이후에는 비교만 한다.

같은 픽스처를 쓰는 이유: 필터·정렬·페이지네이션·분포·집계가 SQL join 한 번에서
projection의 id 집합·순위·필드 조회로 바뀔 때, 경계 조건(판정 없는 공고, 알 수
없는 등급, 마감 없는 공고, 같은 마감)이 그대로 유지되는지를 한 데이터로 본다.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import get_db, init_db
from app.main import app
from app.lifecycle.models import Attachment, Notice, NoticeObservation, Run
from app.screening.models import (
    Counterargument,
    Evidence,
    Judgment,
    MatchedPerformance,
    Perspective,
    Review,
    VerificationAnswer,
    VerificationItem,
)

GOLDEN_PATH = Path(__file__).resolve().parent / "fixtures" / "projection" / "api_responses.json"
WRITE_ENV = "BIDOPS_WRITE_PROJECTION_GOLDEN"

GENERATED_AT = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
PREVIOUS_GENERATED_AT = datetime(2026, 8, 17, 0, 0, tzinfo=timezone.utc)


def _judgment(
    notice: Notice,
    *,
    grade: str | None,
    readiness: str | None = "부분 확인 필요",
    focus: str | None = "AI/데이터",
    summary: str | None = None,
    blocking_items: tuple[str, ...] = (),
    perspectives: tuple[tuple[str, str | None], ...] = (),
) -> Judgment:
    judgment = Judgment(
        notice=notice,
        schema_version="bidops.decisions.v2",
        grade=grade,
        readiness=readiness,
        primary_focus=focus,
        exclusion_category=None,
        summary=summary,
        next_action="담당자 확인",
    )
    for position, (name, assessment) in enumerate(perspectives, start=1):
        perspective = Perspective(
            judgment=judgment,
            position=position,
            name=name,
            assessment=assessment,
            reason=f"{name} 근거",
        )
        perspective.evidence.append(
            Evidence(source="공고명", status="confirmed", fact=f"{name} 사실")
        )
    if perspectives:
        judgment.counterarguments.append(Counterargument(position=1, text="예산이 작을 수 있다"))
        judgment.matched_performances.append(
            MatchedPerformance(
                name="유사 실적", match_reason="같은 축", mismatch_or_limit=None, source="5.2", status="confirmed"
            )
        )
    for item in blocking_items:
        judgment.verification_items.append(
            VerificationItem(item=item, why=f"회사 프로필 5.2의 조달 자격 항목이 {item}", blocking=True, status="미확인")
        )
    if blocking_items:
        judgment.verification_items.append(
            VerificationItem(item="비차단 항목", why="참고", blocking=False, status="확인 완료")
        )
    return judgment


def _build(session: Session) -> dict[str, Any]:
    previous = Run(
        id="20260810-20260816--prev",
        window_from=date(2026, 8, 10),
        window_to=date(2026, 8, 16),
        generated_at=PREVIOUS_GENERATED_AT,
        counts_json={"notices": 1, "judgments": 1, "reviews": 0},
    )
    current = Run(
        id="20260817-20260823--cur",
        window_from=date(2026, 8, 17),
        window_to=date(2026, 8, 23),
        generated_at=GENERATED_AT,
        screening_basis="메타데이터",
        counts_json={
            "notices": 9,
            "judgments": 8,
            "reviews": 2,
            "collection": {"total": 120, "candidate_pool": 30, "audit_pool": 90},
        },
    )
    session.add_all([previous, current])

    def deadline(days: int | None) -> datetime | None:
        return None if days is None else GENERATED_AT + timedelta(days=days)

    specs = [
        # (key, title, agency, role, deadline days, published day, grade, readiness, focus, attachments, blocking)
        ("bid:EQ:000", "AI 플랫폼 구축", "기관 A", "analysis", 3, 20, "우선 검토", "부분 확인 필요", "AI/데이터", ("g2b",), ("참가자격",)),
        ("bid:EQ:001", "데이터 플랫폼 고도화", "기관 B", "analysis", 3, 19, "검토 권장", "확인 완료", "공공 SI·통합관리", ("manual",), ("참가자격", "지역 제한")),
        ("bid:EQ:002", "행사 운영", "기관 A", "analysis", None, 18, "제외", "해당 없음", "해당 없음", (), ()),
        ("bid:EQ:003", "블록체인 DID 플랫폼", "기관 C", "analysis", 10, None, "관찰 대상", "부분 확인 필요", "블록체인·DID", ("g2b", "manual"), ()),
        ("bid:EQ:004", "감사 공고 플랫폼", "기관 D", "audit", 5, 17, "우선 검토", "부분 확인 필요", "AI/데이터", (), ("실적 증빙",)),
        ("bid:EQ:005", "감사 제외 공고", "기관 D", "audit", 30, 16, "제외", "해당 없음", None, (), ()),
        ("bid:EQ:006", "판정 없는 공고", "기관 E", "analysis", 3, 15, None, None, None, ("g2b",), ()),
        ("bid:EQ:007", "알 수 없는 등급", "기관 F", "analysis", 1, 21, "기타", "값 없음 아님", "AI/데이터", (), ()),
        ("bid:EQ:008", "등급만 있는 공고", "기관 G", "analysis", 1, 21, "검토 권장", None, None, (), ()),
    ]
    notices: list[Notice] = []
    judgments: list[Judgment] = []
    for key, title, agency, role, days, published_day, grade, readiness, focus, attachments, blocking in specs:
        notice = Notice(
            run=current,
            notice_key=key,
            bid_no=key.split(":")[1] + "-" + key.split(":")[2],
            bid_ord="000",
            title=title,
            agency=agency,
            published_at=None if published_day is None else datetime(2026, 8, published_day, 9, tzinfo=timezone.utc),
            deadline_at=deadline(days),
            estimated_price=1000000 if role == "analysis" else None,
            sample_role=role,
            sample_stratum="AI/데이터" if focus == "AI/데이터" else "무작위",
            collection_bucket="candidate_pool" if role == "analysis" else "audit_pool",
            lifecycle_json={"unified_notice_no": "UNI-1" if key in {"bid:EQ:000", "bid:EQ:001"} else None, "pre_spec_no": "PRE-1" if key in {"bid:EQ:000", "bid:EQ:003"} else None},
        )
        for origin in attachments:
            notice.attachments.append(
                Attachment(
                    name=f"{origin}.pdf",
                    origin=origin,
                    file_ext="pdf",
                    size_bytes=10,
                    # 응답에 그대로 실리는 값이라 벽시계에 맡기지 않는다.
                    created_at=GENERATED_AT,
                )
            )
        notices.append(notice)
        if grade is not None or readiness is not None:
            judgments.append(
                _judgment(
                    notice,
                    grade=grade,
                    readiness=readiness,
                    focus=focus,
                    summary=f"{title} 요약",
                    blocking_items=blocking,
                    perspectives=(("기술 적합성", "적합"), ("사업성", "확인 불가")) if key in {"bid:EQ:000", "bid:EQ:003"} else (),
                )
            )
    # 첫 공고는 이전 회차에서도 관측됐다 (이력·재현성).
    previous.notice_observations.append(NoticeObservation(notice=notices[0], changed_fields_json=[]))
    # ordinal 관계 후보: 같은 bid_no, 다른 bid_ord.
    ordinal = Notice(
        run=current,
        notice_key="bid:EQ-000:001",
        bid_no="EQ-000",
        bid_ord="001",
        title="AI 플랫폼 구축 정정",
        agency="기관 A",
        published_at=datetime(2026, 8, 22, 9, tzinfo=timezone.utc),
        sample_role="analysis",
        lifecycle_json={"change_reason": "정정"},
    )
    notices.append(ordinal)
    judgments.append(_judgment(ordinal, grade="관찰 대상", readiness="확인 완료", focus="AI/데이터"))
    session.add_all(notices)
    session.add_all(judgments)
    session.flush()

    reviews = [
        Review(
            notice=notices[0],
            run=current,
            disposition="심층 검토 진행",
            system_judgment_review="동의",
            corrected_grade=None,
            corrected_readiness=None,
            weakest_perspective="사업성",
            reason="첫 리뷰",
            reviewer="담당자",
            created_at=GENERATED_AT + timedelta(hours=1),
            updated_at=GENERATED_AT + timedelta(hours=2),
        ),
        Review(
            notice=notices[1],
            run=current,
            disposition="관찰",
            system_judgment_review="근거 부족",
            corrected_grade="관찰 대상",
            corrected_readiness="확인 완료",
            weakest_perspective=None,
            reason="수정",
            reviewer="담당자",
            created_at=GENERATED_AT + timedelta(hours=3),
            updated_at=GENERATED_AT + timedelta(hours=4),
        ),
    ]
    reviews[0].answers.append(VerificationAnswer(item="참가자격", answer="확인 중"))
    session.add_all(reviews)
    session.commit()
    return {
        "run_ids": [current.id, previous.id],
        "notice_ids": [notice.id for notice in notices],
    }


@pytest.fixture
def equivalence_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)
    with Session(engine) as session:
        shape = _build(session)

        def override_db():
            yield session

        app.dependency_overrides[get_db] = override_db
        try:
            with TestClient(app) as client:
                yield client, shape
        finally:
            app.dependency_overrides.pop(get_db, None)


def _requests(shape: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    run_id = shape["run_ids"][0]
    previous_run_id = shape["run_ids"][1]
    calls: list[tuple[str, str, dict[str, Any]]] = []
    pages = [(50, 0), (2, 0), (2, 2), (3, 1)]
    for grade, sort, (limit, offset) in product([None, "all", "우선 검토", "제외"], ["deadline", "grade", "published"], pages):
        params: dict[str, Any] = {"run_id": run_id, "sort": sort, "limit": limit, "offset": offset}
        if grade is not None:
            params["grade"] = grade
        calls.append((f"notices grade={grade} sort={sort} page={limit}/{offset}", "/api/notices", params))
    for sort in ["deadline", "grade"]:
        for extra in (
            {"readiness": "부분 확인 필요"},
            {"focus": "AI/데이터"},
            {"grade": "all", "readiness": "확인 완료"},
            {"sample_role": "all"},
            {"sample_role": "audit"},
            {"sample_role": "all", "grade": "all"},
            {"attachment": "none"},
            {"attachment": "manual"},
            {"q": "플랫폼"},
            {"q": "기관 D", "sample_role": "all", "grade": "all"},
        ):
            params = {"run_id": run_id, "sort": sort, **extra}
            calls.append((f"notices {sorted(extra.items())} sort={sort}", "/api/notices", params))
    for notice_id in shape["notice_ids"]:
        calls.append((f"notice detail {notice_id}", f"/api/notices/{notice_id}", {}))
        calls.append((f"notice related {notice_id}", f"/api/notices/{notice_id}/related", {}))
        calls.append((f"notice history {notice_id}", f"/api/notices/{notice_id}/history", {}))
    for target in (run_id, previous_run_id):
        calls.append((f"run stats {target}", f"/api/runs/{target}/stats", {}))
        calls.append((f"run detail counts {target}", f"/api/runs/{target}", {}))
        calls.append((f"metrics {target}", "/api/metrics/validation", {"run_id": target}))
        calls.append((f"reviews {target}", "/api/reviews", {"run_id": target}))
        calls.append((f"reviews export {target}", "/api/reviews/export", {"run_id": target}))
    calls.append(("runs", "/api/runs", {}))
    return calls


def _normalize(label: str, body: Any) -> Any:
    """비교 전에 **이전 구현이 정하지 않았던 두 순서**만 고정한다.

    둘 다 이전 코드가 ORDER BY 없는 조회의 반환 순서를 그대로 실은 자리이며,
    같은 코드가 실행 프로세스에 따라 다른 순서를 내는 것을 확인했다. 즉 이 순서는
    지킬 계약이 아니라 고정되지 않은 값이었다. 이번 변경은 두 자리 모두 결정적
    기준으로 고정하지만(확인 항목의 공고 집합은 식별자 순, 마감 임박 목록은
    마감 → 식별자 순), golden은 그 이전의 임의 순서를 담고 있으므로 비교 전에
    양쪽을 같은 기준으로 정렬한다. **그 밖의 필드는 순서까지 그대로 같아야 한다.**
    """

    if not isinstance(body, dict):
        return body
    if isinstance(body.get("verification_requests"), list):
        body = {
            **body,
            "verification_requests": [
                {**item, "notice_pks": sorted(item.get("notice_pks", []))}
                for item in body["verification_requests"]
            ],
        }
    if isinstance(body.get("imminent_deadlines"), list):
        body = {
            **body,
            "imminent_deadlines": sorted(
                body["imminent_deadlines"],
                key=lambda item: (item.get("deadline_at") or "", item.get("id") or 0),
            ),
        }
    return body


def _capture(client: TestClient, shape: dict[str, Any]) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    for label, path, params in _requests(shape):
        response = client.get(path, params=params)
        try:
            body: Any = response.json()
        except ValueError:
            body = response.text
        if isinstance(body, dict):
            # run detail은 파일 시스템의 산출물 존재 여부를 함께 담으므로 counts만 본다.
            if label.startswith("run detail counts"):
                body = {"run_id": body.get("run_id"), "counts": body.get("counts")}
        captured[label] = {"status": response.status_code, "body": _normalize(label, body)}
    return captured


def test_judgment_dependent_responses_match_the_golden(equivalence_client):
    client, shape = equivalence_client
    captured = _capture(client, shape)
    if os.environ.get(WRITE_ENV) == "1":
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        GOLDEN_PATH.write_text(
            json.dumps(captured, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    golden = {
        label: {**value, "body": _normalize(label, value["body"])}
        for label, value in json.loads(GOLDEN_PATH.read_text(encoding="utf-8")).items()
    }
    assert set(captured) == set(golden)
    mismatched = [label for label in golden if captured[label] != golden[label]]
    assert not mismatched, "\n".join(
        f"{label}\n  expected: {json.dumps(golden[label], ensure_ascii=False)[:600]}\n  actual:   {json.dumps(captured[label], ensure_ascii=False)[:600]}"
        for label in mismatched[:10]
    )
    # golden이 실제로 판정 의존 응답을 담고 있는지 — 빈 목록만 비교하는 실수를 막는다.
    default_list = golden["notices grade=None sort=deadline page=50/0"]["body"]
    assert default_list["total"] > 0
    assert any(item["grade"] for item in default_list["items"])
    assert golden[f"run stats {shape['run_ids'][0]}"]["body"]["grade_distribution"]
    assert golden[f"metrics {shape['run_ids'][0]}"]["body"]["metrics"][1]["value"] is not None
