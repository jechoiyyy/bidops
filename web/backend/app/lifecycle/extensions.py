"""lifecycle 확장점: 인터페이스와 프로세스 전역 registry (명세 §6).

lifecycle은 자기 화면·흐름이 다른 모듈의 결과를 함께 써야 하는 자리를 여기에
확장점으로 정의한다. **lifecycle은 어느 모듈이 그것을 제공하는지 알지 못한다** —
등록하는 쪽이 능력(capability)을 채우고, lifecycle은 registry에 무엇이 있는지만
본다. 제공자가 없으면 registry의 기본 구현이 §6.1·§6.2가 정한 "부재 시" 값을
돌려주므로, 호출부는 제공자 유무로 분기하지 않는다.

등록은 조립 계층이 **앱 객체를 조립할 때** 한다(router 등록과 같은 시점, lifespan이
아니다). runtime을 만들지 않는 격리 API 테스트에서도 projection이 있어야 하기
때문이다. 등록은 import와 객체 생성일 뿐이고 migration·seed·모델 호출을 하지
않는다(§9).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "ExtensionRegistry",
    "JudgmentProjection",
    "OverviewDocumentProjection",
    "PreSpecDocumentCounts",
    "RunIngestCounts",
    "RunIngestHook",
    "RunDirectoryClaim",
    "TrackingDecisionHook",
    "extension_registry",
    "reset_extension_registry",
]


# --- 6.1 읽기 projection ----------------------------------------------------


@runtime_checkable
class JudgmentProjection(Protocol):
    """공고 판정 결과를 lifecycle 화면에 실어 주는 확장점 (§6.1 첫째 행).

    회차 하나가 최대 약 2,000건이므로 구현은 **회차 단위로 한 번에** 읽어
    메모리에서 결합한다. 공고당 조회(N+1)를 만들지 않는다.
    """

    def notice_fields(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, Mapping[str, Any]]:
        """공고별 `grade`·`readiness`·`focus`. 판정이 없는 공고는 빠뜨려도 된다."""

    def notice_ids_for_filters(
        self,
        session: Any,
        *,
        run_id: str | None = None,
        grade: str | None = None,
        readiness: str | None = None,
        focus: str | None = None,
    ) -> Sequence[int]:
        """등급·준비·focus 필터를 통과하는 공고 id. 순서는 무의미하다.

        필터가 모두 `None`이면 기본 조건(현재 `Judgment.grade != "제외"`)을
        적용한 집합을 돌려준다. 그 기본 조건은 projection의 일부이므로 제공자가
        없을 때는 적용되지 않는다(§6.1).
        """

    def grade_rank(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, int]:
        """`sort=grade`가 쓰는 공고별 등급 순위. 판정이 없으면 빠뜨린다."""

    def notice_detail(self, session: Any, notice_id: int) -> Mapping[str, Any]:
        """상세의 `judgment`·`reviews`. 없으면 빈 mapping."""

    def run_stats(self, session: Any, run_id: str) -> Mapping[str, Any]:
        """회차 통계의 grade/readiness/focus 분포와 `verification_requests`."""

    def metrics_input(self, session: Any, run_ids: Sequence[str]) -> Mapping[str, Any]:
        """검증 지표 집계 입력."""


@dataclass(frozen=True)
class PreSpecDocumentCounts:
    """공고별 첨부 취득 상태 건수 (§6.1 둘째 행).

    응답 모델(`PreSpecDocumentSummary`)이 `ge=0` 정수라 `null`을 못 받으므로
    제공자가 없을 때는 다섯 값이 모두 0이다. `attachments`는 lifecycle이 자기
    `attachment` 테이블에서 직접 세므로 여기에 없다.
    """

    completed: int = 0
    pending: int = 0
    running: int = 0
    blocked: int = 0
    failed: int = 0


@runtime_checkable
class OverviewDocumentProjection(Protocol):
    """사전규격 개요·문서 준비 상태를 lifecycle 목록에 실어 주는 확장점."""

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        """공고별 개요 검토 상태. 없는 공고는 빠뜨린다(호출부가 `None`으로 채운다)."""

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        """상태별 건수. 제공자가 없으면 빈 map."""

    def document_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, PreSpecDocumentCounts]:
        """공고별 첨부 취득 상태 건수. 없는 공고는 빠뜨린다(호출부가 0으로 채운다)."""


# --- 6.2 이벤트 hook --------------------------------------------------------


@dataclass(frozen=True)
class RunDirectoryClaim:
    """"이 회차 디렉터리는 내 전용 결과다"라는 hook의 응답 (§6.2).

    lifecycle `ingest_run`은 공고를 읽기 전에 등록된 hook에 디렉터리를 보여 주고,
    어느 hook이 이것을 돌려주면 Run upsert(또는 존재 확인)만 한 뒤 곧바로 그
    hook의 적재 단계를 호출하고 공고 적재를 건너뛴다. 감지와 `source_run_id`
    검증은 전부 hook 안에서 일어난다.
    """

    source_run_id: str
    load: Any
    """`(session, directory, **options) -> RunIngestCounts` 를 만족하는 호출 가능 객체."""


@dataclass(frozen=True)
class RunIngestCounts:
    """회차 적재 hook이 돌려주는 건수 (§6.2 마지막 문단).

    `IngestResponse`의 `judgments`·`reviews`, `IngestResult`의 C-2 건수,
    `RunSummary.counts`를 이 값으로 채운다. 제공자가 없으면 모두 0이고, 호출부가
    `warnings`에 건너뛰었음을 남긴다 — 계약상 이 정수 필드는 `null`을 허용하지
    않는다.
    """

    judgments: int = 0
    reviews: int = 0
    order_plans: int = 0
    screening_executions: int = 0
    screening_attempts: int = 0
    screening_results: int = 0
    screening_artifacts: int = 0
    screening_feedback: int = 0
    warnings: tuple[Mapping[str, Any], ...] = ()

    def merged_with(self, other: RunIngestCounts) -> RunIngestCounts:
        """여러 hook의 건수를 합친다. 등록 순서대로 누적된다."""

        return RunIngestCounts(
            judgments=self.judgments + other.judgments,
            reviews=self.reviews + other.reviews,
            order_plans=self.order_plans + other.order_plans,
            screening_executions=self.screening_executions + other.screening_executions,
            screening_attempts=self.screening_attempts + other.screening_attempts,
            screening_results=self.screening_results + other.screening_results,
            screening_artifacts=self.screening_artifacts + other.screening_artifacts,
            screening_feedback=self.screening_feedback + other.screening_feedback,
            warnings=self.warnings + other.warnings,
        )


@runtime_checkable
class RunIngestHook(Protocol):
    """회차가 적재된 뒤 같은 transaction 안에서 불리는 확장점 (§6.2 첫째 행)."""

    def inspect_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        """공고를 읽기 전에 이 디렉터리가 자기 전용 결과인지 답한다. 아니면 `None`."""

    def run_ingested(self, session: Any, run_id: str, directory: Path) -> RunIngestCounts:
        """공고·발주계획·첨부 메타 적재가 끝난 뒤, 같은 session에서 불린다."""


@runtime_checkable
class TrackingDecisionHook(Protocol):
    """추적 결정이 바뀐 뒤 불리는 확장점 (§6.2 둘째 행)."""

    def tracking_decision_changed(self, session: Any, opportunity_id: Any) -> None:
        """`PATCH /api/opportunities/{id}/tracking-status` 처리 뒤에 불린다."""


# --- registry ---------------------------------------------------------------


class _AbsentJudgmentProjection:
    """제공자가 없을 때의 판정 projection (§6.1 "제공자 부재 시").

    필드는 `null`, 분포는 빈 목록이다. 필터·정렬이 422가 되어야 하는 자리는 값이
    아니라 "지원하지 않는다"는 사실이어야 하므로 registry의
    `judgment_filters_supported`가 판단한다 — 여기서는 필터 없는 전체 집합만
    돌려준다(기본 조건 `Judgment.grade != "제외"`도 projection의 일부이므로
    적용되지 않는다).
    """

    def notice_fields(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, Mapping[str, Any]]:
        return {}

    def notice_ids_for_filters(
        self,
        session: Any,
        *,
        run_id: str | None = None,
        grade: str | None = None,
        readiness: str | None = None,
        focus: str | None = None,
    ) -> Sequence[int]:
        return ()

    def grade_rank(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, int]:
        return {}

    def notice_detail(self, session: Any, notice_id: int) -> Mapping[str, Any]:
        return {}

    def run_stats(self, session: Any, run_id: str) -> Mapping[str, Any]:
        return {}

    def metrics_input(self, session: Any, run_ids: Sequence[str]) -> Mapping[str, Any]:
        return {}


class _AbsentOverviewDocumentProjection:
    """제공자가 없을 때의 개요·문서 projection (§6.1 "제공자 부재 시")."""

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        return {}

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        return {}

    def document_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, PreSpecDocumentCounts]:
        return {}


@dataclass
class ExtensionRegistry:
    """프로세스 전역 단일 확장점 registry.

    lifecycle은 여기에 무엇이 있는지만 본다. 제공자가 없어도 projection 접근자는
    항상 객체를 돌려주므로 호출부가 `None` 분기를 하지 않는다. 필터·정렬을 422로
    거절해야 하는 자리만 `*_supported` 술어를 본다.
    """

    _judgment: JudgmentProjection | None = None
    _overview: OverviewDocumentProjection | None = None
    _run_ingest_hooks: list[RunIngestHook] = field(default_factory=list)
    _tracking_hooks: list[TrackingDecisionHook] = field(default_factory=list)

    _absent_judgment: Any = field(default_factory=_AbsentJudgmentProjection, repr=False)
    _absent_overview: Any = field(default_factory=_AbsentOverviewDocumentProjection, repr=False)

    # --- 등록 (조립 계층이 앱 조립 시점에 호출한다) ---
    def register_judgment_projection(self, projection: JudgmentProjection) -> None:
        if self._judgment is not None:
            raise RuntimeError("판정 projection 제공자가 이미 등록됐다")
        self._judgment = projection

    def register_overview_document_projection(self, projection: OverviewDocumentProjection) -> None:
        if self._overview is not None:
            raise RuntimeError("개요·문서 projection 제공자가 이미 등록됐다")
        self._overview = projection

    def register_run_ingest_hook(self, hook: RunIngestHook) -> None:
        self._run_ingest_hooks.append(hook)

    def register_tracking_decision_hook(self, hook: TrackingDecisionHook) -> None:
        self._tracking_hooks.append(hook)

    # --- 조회 (lifecycle이 호출한다) ---
    @property
    def judgment_projection(self) -> JudgmentProjection:
        return self._judgment if self._judgment is not None else self._absent_judgment

    @property
    def judgment_filters_supported(self) -> bool:
        """`grade`·`readiness`·`focus` 필터와 `sort=grade`를 받아도 되는가.

        제공자가 없으면 그 query는 422다(§6.1). 이것은 모듈 이름이 아니라 능력을
        묻는 술어다.
        """

        return self._judgment is not None

    @property
    def overview_document_projection(self) -> OverviewDocumentProjection:
        return self._overview if self._overview is not None else self._absent_overview

    @property
    def overview_filters_supported(self) -> bool:
        """개요 상태 필터를 받아도 되는가. 제공자가 없으면 422다(§6.1)."""

        return self._overview is not None

    # --- hook 실행 (등록 순서대로, 호출자가 넘긴 session에서 동기적으로) ---
    def claim_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        """등록된 hook에 디렉터리를 보여 준다. 아무도 답하지 않으면 `None`."""

        for hook in self._run_ingest_hooks:
            claim = hook.inspect_run_directory(directory)
            if claim is not None:
                return claim
        return None

    def run_ingested(self, session: Any, run_id: str, directory: Path) -> RunIngestCounts:
        """등록 순서대로 실행하고 건수를 합친다. hook이 없으면 모두 0이다."""

        counts = RunIngestCounts()
        for hook in self._run_ingest_hooks:
            counts = counts.merged_with(hook.run_ingested(session, run_id, directory))
        return counts

    def tracking_decision_changed(self, session: Any, opportunity_id: Any) -> None:
        """등록 순서대로 실행한다. hook이 없으면 아무 일도 하지 않는다."""

        for hook in self._tracking_hooks:
            hook.tracking_decision_changed(session, opportunity_id)

    @property
    def run_ingest_hook_count(self) -> int:
        return len(self._run_ingest_hooks)

    @property
    def tracking_decision_hook_count(self) -> int:
        return len(self._tracking_hooks)


_REGISTRY = ExtensionRegistry()


def extension_registry() -> ExtensionRegistry:
    """프로세스 전역 registry."""

    return _REGISTRY


def reset_extension_registry() -> ExtensionRegistry:
    """registry를 빈 상태로 되돌린다.

    프로세스 전역 단일 객체이므로 테스트가 서로 오염되지 않도록 fixture에서
    쓴다. 운영 경로는 호출하지 않는다.
    """

    global _REGISTRY
    _REGISTRY = ExtensionRegistry()
    return _REGISTRY
