"""lifecycle 확장점 registry의 계약 (명세 §6).

여기서 고정하는 것은 세 가지다. (1) 제공자가 없을 때 §6.1 표의 "부재 시" 값이
그대로 나온다. (2) hook은 등록 순서대로 동기 실행되고, 없으면 아무 일도 하지
않는다. (3) 회차 적재 hook의 건수가 합산돼 돌아온다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.lifecycle.extensions import (
    ExtensionRegistry,
    PreSpecDocumentCounts,
    RunDirectoryClaim,
    RunIngestCounts,
    extension_registry,
    reset_extension_registry,
)


@pytest.fixture()
def registry() -> ExtensionRegistry:
    """프로세스 전역 registry를 테스트마다 빈 상태로 되돌린다."""

    yield reset_extension_registry()
    reset_extension_registry()


# --- 제공자 부재 시 (§6.1) ---------------------------------------------------


def test_absent_judgment_projection_yields_null_fields_and_empty_distributions(registry):
    projection = registry.judgment_projection

    assert projection.notice_fields(None, [1, 2, 3]) == {}
    assert projection.notice_detail(None, 1) == {}
    assert projection.grade_rank(None, [1, 2]) == {}
    assert projection.run_stats(None, "r1") == {}
    assert projection.metrics_input(None, ["r1"]) == {}


def test_absent_judgment_projection_does_not_apply_the_default_exclusion(registry):
    """기본 조건 `Judgment.grade != "제외"`도 projection의 일부다 (§6.1).

    제공자가 없으면 그 조건이 적용되지 않아야 하므로, 필터 없는 호출이 "걸러진
    집합"을 돌려주면 안 된다. registry는 빈 집합을 돌려주고 호출부가 필터를
    적용하지 않는 쪽으로 해석한다.
    """

    assert tuple(registry.judgment_projection.notice_ids_for_filters(None)) == ()


def test_judgment_filters_are_unsupported_without_a_provider(registry):
    """등급·준비·focus 필터와 sort=grade가 422가 되어야 하는 근거 (§6.1)."""

    assert registry.judgment_filters_supported is False


def test_absent_overview_projection_yields_null_status_and_zero_document_counts(registry):
    projection = registry.overview_document_projection

    assert projection.overview_status(None, [1, 2]) == {}
    assert projection.overview_status_counts(None, [1, 2]) == {}
    assert projection.document_counts(None, [1, 2]) == {}
    assert registry.overview_filters_supported is False


def test_prespec_document_counts_default_to_zero_because_the_contract_forbids_null():
    """`PreSpecDocumentSummary`의 다섯 건수는 `ge=0` 정수라 `null`이 될 수 없다."""

    counts = PreSpecDocumentCounts()

    assert (counts.completed, counts.pending, counts.running, counts.blocked, counts.failed) == (0, 0, 0, 0, 0)


# --- 등록과 조회 -------------------------------------------------------------


class _Judgment:
    def notice_fields(self, session, notice_ids):
        return {int(pk): {"grade": "우선 검토", "readiness": "확인 완료", "focus": "f"} for pk in notice_ids}

    def notice_ids_for_filters(self, session, *, run_id=None, grade=None, readiness=None, focus=None):
        return (7,)

    def grade_rank(self, session, notice_ids):
        return {int(pk): 0 for pk in notice_ids}

    def notice_detail(self, session, notice_id):
        return {"judgment": {"grade": "우선 검토"}, "reviews": []}

    def run_stats(self, session, run_id):
        return {"grade": [{"label": "우선 검토", "count": 1}]}

    def metrics_input(self, session, run_ids):
        return {"runs": list(run_ids)}


def test_registered_judgment_projection_replaces_the_absent_default(registry):
    registry.register_judgment_projection(_Judgment())

    assert registry.judgment_filters_supported is True
    assert registry.judgment_projection.notice_fields(None, [4])[4]["grade"] == "우선 검토"
    assert tuple(registry.judgment_projection.notice_ids_for_filters(None, grade="우선 검토")) == (7,)


def test_a_second_judgment_provider_is_refused(registry):
    """projection은 모듈 하나가 제공한다. 두 번째 등록은 조립 오류다."""

    registry.register_judgment_projection(_Judgment())

    with pytest.raises(RuntimeError):
        registry.register_judgment_projection(_Judgment())


# --- hook (§6.2) -------------------------------------------------------------


class _RunHook:
    def __init__(self, label: str, order: list[str], *, claim_dir: str | None = None, counts: RunIngestCounts | None = None):
        self.label = label
        self.order = order
        self.claim_dir = claim_dir
        self.counts = counts or RunIngestCounts()

    def inspect_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        if self.claim_dir is not None and directory.name == self.claim_dir:
            return RunDirectoryClaim(source_run_id=f"src-{self.label}", load=lambda *a, **k: self.counts)
        return None

    def run_ingested(self, session, run_id: str, directory: Path) -> RunIngestCounts:
        self.order.append(self.label)
        return self.counts


class _TrackingHook:
    def __init__(self, label: str, order: list[str]):
        self.label = label
        self.order = order

    def tracking_decision_changed(self, session, opportunity_id) -> None:
        self.order.append(self.label)


def test_no_hook_registered_is_a_no_op(registry):
    order: list[str] = []

    assert registry.run_ingested(None, "r1", Path("/tmp/r1")) == RunIngestCounts()
    assert registry.claim_run_directory(Path("/tmp/r1")) is None
    registry.tracking_decision_changed(None, 1)

    assert order == []
    assert registry.run_ingest_hook_count == 0
    assert registry.tracking_decision_hook_count == 0


def test_hooks_run_in_registration_order(registry):
    order: list[str] = []
    registry.register_run_ingest_hook(_RunHook("first", order))
    registry.register_run_ingest_hook(_RunHook("second", order))
    registry.register_tracking_decision_hook(_TrackingHook("t-first", order))
    registry.register_tracking_decision_hook(_TrackingHook("t-second", order))

    registry.run_ingested(None, "r1", Path("/tmp/r1"))
    registry.tracking_decision_changed(None, 1)

    assert order == ["first", "second", "t-first", "t-second"]


def test_run_ingest_counts_are_summed_across_hooks(registry):
    order: list[str] = []
    registry.register_run_ingest_hook(
        _RunHook("a", order, counts=RunIngestCounts(judgments=3, reviews=1, warnings=({"level": "warning"},)))
    )
    registry.register_run_ingest_hook(
        _RunHook("b", order, counts=RunIngestCounts(judgments=2, order_plans=5, screening_results=5))
    )

    counts = registry.run_ingested(None, "r1", Path("/tmp/r1"))

    assert counts.judgments == 5
    assert counts.reviews == 1
    assert counts.order_plans == 5
    assert counts.screening_results == 5
    assert counts.warnings == ({"level": "warning"},)


def test_directory_claim_comes_from_the_first_hook_that_answers(registry):
    """C-2 전용 결과 디렉터리 판정은 hook 안에서 일어난다 (§6.2)."""

    order: list[str] = []
    registry.register_run_ingest_hook(_RunHook("silent", order))
    registry.register_run_ingest_hook(
        _RunHook("owner", order, claim_dir="c2-run", counts=RunIngestCounts(screening_results=9))
    )

    claim = registry.claim_run_directory(Path("/data/runs/c2-run"))

    assert claim is not None
    assert claim.source_run_id == "src-owner"
    assert claim.load(None, Path("/data/runs/c2-run")).screening_results == 9
    # 다른 디렉터리는 아무도 답하지 않는다 → 일반 회차로 처리된다.
    assert registry.claim_run_directory(Path("/data/runs/ordinary")) is None


def test_the_first_hook_that_claims_a_directory_wins(registry):
    """둘 이상이 같은 디렉터리를 주장하면 **먼저 등록된** 쪽이 이긴다.

    등록 순서가 `BIDOPS_MODULES` 순서이므로(§6.2), 나중 등록이 앞 등록을 덮으면
    같은 설정에서 적재 주체가 뒤바뀐다.
    """

    order: list[str] = []
    registry.register_run_ingest_hook(
        _RunHook("early", order, claim_dir="c2-run", counts=RunIngestCounts(screening_results=1))
    )
    registry.register_run_ingest_hook(
        _RunHook("late", order, claim_dir="c2-run", counts=RunIngestCounts(screening_results=2))
    )

    claim = registry.claim_run_directory(Path("/data/runs/c2-run"))

    assert claim is not None
    assert claim.source_run_id == "src-early"


def test_the_global_registry_is_one_object(registry):
    assert extension_registry() is registry
    registry.register_judgment_projection(_Judgment())
    assert extension_registry().judgment_filters_supported is True


def test_reset_gives_a_fresh_registry(registry):
    registry.register_judgment_projection(_Judgment())
    assert registry.judgment_filters_supported is True

    fresh = reset_extension_registry()

    assert fresh is not registry
    assert fresh.judgment_filters_supported is False
    assert extension_registry() is fresh
