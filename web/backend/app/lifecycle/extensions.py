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
    "EffectiveGradeChangedHook",
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
    "restore_extension_registry",
]


# --- 6.1 읽기 projection ----------------------------------------------------


@runtime_checkable
class JudgmentProjection(Protocol):
    """공고 판정 결과를 lifecycle 화면에 실어 주는 확장점 (§6.1 첫째 행).

    회차 하나가 최대 약 2,000건이므로 구현은 **회차 단위로 한 번에** 읽어
    메모리에서 결합한다. 공고당 조회(N+1)를 만들지 않는다. 회차 경계가 없는
    사용처(누적 목록)에서는 그 상한이 성립하지 않으므로, 호출부가 넘긴
    `notice_ids` 만큼을 상수 회 조회로 처리한다.
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
    ) -> Sequence[int] | None:
        """공고 집합을 이 projection이 어떻게 제한하는가. 순서는 무의미하다.

        **`None`은 "제한하지 않음"이고 빈 sequence는 "0건 일치"다.** 둘을 같은
        값으로 표현하면 §6.1이 경고한 실패 모드가 그대로 난다 — 제공자가 없을 때
        전체 공고가 보여야 하는데 아무것도 보이지 않게 되거나 그 반대가 된다.
        호출부는 `None`이면 공고 집합에 조건을 걸지 않고, sequence면 그 id로만
        제한한다.

        필터가 모두 `None`이면 기본 조건(현재 `Judgment.grade != "제외"`)을 적용한
        집합을 돌려준다. 그 기본 조건은 projection의 일부이므로 제공자가 없을 때는
        적용되지 않아야 하고, 그것이 곧 `None`(제한 없음)이다(§6.1).
        """

    def grade_rank(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, int]:
        """`sort=grade`가 쓰는 공고별 등급 순위. 판정이 없으면 빠뜨린다."""

    def notice_detail(self, session: Any, notice_id: int) -> Mapping[str, Any]:
        """상세의 `judgment`·`reviews`. 없으면 빈 mapping."""

    def run_stats(self, session: Any, run_id: str) -> Mapping[str, Any]:
        """`GET /api/runs/{id}/stats`에서 판정이 채우는 부분 전부.

        `RunStatsResponse`에서 판정에 기대는 필드는 분포 셋만이 아니다. 구현은
        아래를 모두 채운다 — 빠뜨리면 응답의 그 필드가 조용히 0/빈 목록이 된다.

        - `grade_distribution`·`readiness_distribution`·`focus_distribution`
        - `verification_requests`
        - `priority_review_count`·`audit_missed_count`
        - `funnel`의 판정 단계 항목
        - `imminent_deadlines` 각 항목의 `blocking_verification_items`

        회차에 속하지 않는 값(`timezone`, `generated_at`, `sample_count`,
        `collected_count`, `candidate_count`, 마감 임박 공고 자체)은 lifecycle이
        자기 데이터로 채운다. 제공자가 없으면 위 목록은 빈 목록·0이다(§6.1).
        """

    def metrics_input(self, session: Any, run_ids: Sequence[str]) -> Mapping[str, Any]:
        """`GET /api/metrics/*`의 검증 지표가 판정에 기대는 입력.

        지표 다섯 개(재현성·판별력·근거 타당성·정보 충분성·관점 분리) 전부가
        판정·리뷰 데이터에서 나온다. **재현성만 회차 범위를 벗어나 전체를 훑는다**
        (`services/metrics.py`의 `_reproducibility`) — 그래서 `run_ids`를 받고,
        구현이 그 지표에 한해 범위를 넓힌다.

        임계값 판단과 "측정 불가" 사유 라벨은 지표 정의의 일부이므로 **구현이**
        조립해 돌려준다. lifecycle은 그것을 응답 모델에 옮기기만 하고 지표의
        의미를 알지 못한다. 제공자가 없으면 빈 mapping이고, 호출부는 지표를
        "측정 불가"로 낸다(§6.1).
        """


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
    """사전규격 개요·문서 준비 상태를 lifecycle 목록에 실어 주는 확장점.

    `GET /api/pre-specs`는 회차 범위가 아니라 누적 목록이다. 따라서 "회차당 약
    2,000건"이라는 상한이 여기에는 적용되지 않는다 — 구현은 호출부가 넘긴
    `notice_ids` 만큼을 상수 회 조회로 처리해야 하고, 목록이 길어져도 공고당
    조회를 만들지 않는다.
    """

    def overview_status(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, str]:
        """공고별 개요 검토 상태. 없는 공고는 빠뜨린다(호출부가 `None`으로 채운다)."""

    def overview_status_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[str, int]:
        """상태별 건수. 제공자가 없으면 빈 map."""

    def document_counts(self, session: Any, notice_ids: Sequence[int]) -> Mapping[int, PreSpecDocumentCounts]:
        """공고별 첨부 취득 상태 건수. 없는 공고는 빠뜨린다(호출부가 0으로 채운다)."""

    def prespec_status_fields(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, Any]]:
        """등급과 자동 준비 상태 (명세 §8).

        키는 `grade`·`grade_source`·`auto_preparation_status`·
        `auto_preparation_reason`·`latest_deep_review_id`다. 등급은 판정도 정정도
        없으면 `None`이고 그때 `grade_source`도 `None`이다 — 둘을 특정 값으로
        접지 않는다.

        `document_counts`와 같은 계약이다: 호출부가 넘긴 `notice_ids` 만큼을
        **상수 회 조회**로 처리하고 공고당 조회를 만들지 않는다. 없는 공고는
        빠뜨린다(호출부가 부재 기본값으로 채운다).
        """


# --- 6.2 이벤트 hook --------------------------------------------------------


@runtime_checkable
class ClaimedDirectoryLoad(Protocol):
    """주장한 hook이 그 디렉터리를 직접 적재하는 단계 (§6.2).

    인자 순서와 이름을 여기서 못박는다. 대체 대상인
    `load_order_plan_screening(run_directory, session, *, policy_path, binding_path)`
    과 순서가 다르므로, 구현하는 쪽이 어댑터에서 맞춰 넘겨야 한다 — `Any`로
    두면 그 불일치가 런타임까지 숨는다.
    """

    def __call__(
        self,
        session: Any,
        directory: Path,
        *,
        policy_path: Path | None = None,
        binding_path: Path | None = None,
    ) -> RunIngestCounts: ...


@dataclass(frozen=True)
class RunDirectoryClaim:
    """"이 회차 디렉터리는 내 전용 결과다"라는 hook의 응답 (§6.2).

    lifecycle `ingest_run`은 공고를 읽기 전에 등록된 hook에 디렉터리를 보여 주고,
    어느 hook이 이것을 돌려주면 Run upsert(또는 존재 확인)만 한 뒤 곧바로 그
    hook의 적재 단계를 호출하고 공고 적재를 건너뛴다. 감지와 `source_run_id`
    검증은 전부 hook 안에서 일어난다.
    """

    source_run_id: str
    load: ClaimedDirectoryLoad


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
    # `IngestResult`가 `judgments`·`reviews`와 나란히 노출하는 v3 binding 계보다.
    # hook 경로로 옮기면서 이것을 실어 나를 수단이 없으면 조용한 기능 퇴행이 된다.
    # v2 회차에는 의도적으로 없으므로 `None`이 정상이다.
    generation_config: Mapping[str, Any] | None = None
    generation_config_digest: str | None = None

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
            # 회차 하나의 binding은 하나다. 뒤에 등록된 hook이 값을 갖고 있으면
            # 그것이 이기고, 없으면 앞의 값을 지킨다.
            generation_config=(
                other.generation_config if other.generation_config is not None else self.generation_config
            ),
            generation_config_digest=(
                other.generation_config_digest
                if other.generation_config_digest is not None
                else self.generation_config_digest
            ),
        )


@runtime_checkable
class RunIngestHook(Protocol):
    """회차가 적재된 뒤 같은 transaction 안에서 불리는 확장점 (§6.2 첫째 행)."""

    def inspect_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        """공고를 읽기 전에 이 디렉터리가 자기 전용 결과인지 답한다. 아니면 `None`."""

    def run_ingested(
        self,
        session: Any,
        run_id: str,
        directory: Path,
        *,
        reports_root: Path | None = None,
    ) -> RunIngestCounts:
        """공고·발주계획·첨부 메타 적재가 끝난 뒤, 같은 session에서 불린다.

        `reports_root`는 `ingest_run(reports_root=...)`이 받은 값 그대로다. 회차
        디렉터리 옆이 아니라 보고서 트리에 놓이는 산출물(초기 리뷰 가져오기의
        `review-feedback.yaml`)을 hook이 찾을 수 있게 넘긴다. `None`이면 hook이
        `ingest_run`과 같은 기본 위치(`<runs>/../reports`)를 쓴다.
        """


@runtime_checkable
class EffectiveGradeChangedHook(Protocol):
    """공고의 effective grade가 달라졌을 수 있다고 알리는 확장점 (§6.2 둘째 촉발).

    `PUT /api/notices/{pk}/review`가 `corrected_grade`를 바꾼 뒤 판정을 소유한
    모듈이 이 확장점을 부른다. **부르는 쪽은 누가 구현했는지 알지 못한다** —
    registry만 본다. 제공자가 없으면 no-op이다.

    구현은 자기 실패를 savepoint로 가둔다. 한 hook의 실패가 형제 hook의 성공
    쓰기나 리뷰 저장 자체를 되돌리면 안 되기 때문이다(§6.2).
    """

    def effective_grade_changed(self, session: Any, notice_ids: Sequence[int]) -> None:
        """등급이 달라졌을 수 있는 공고들. 호출자가 넘긴 session에서 동기 실행된다."""


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
    `judgment_filters_supported`가 판단한다.

    `notice_ids_for_filters`는 `None`(= 공고 집합을 제한하지 않음)을 돌려준다.
    기본 조건 `Judgment.grade != "제외"`도 projection의 일부라 적용되지 않으므로,
    제공자가 없으면 **전체 공고가 보인다**(§6.1).
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
    ) -> Sequence[int] | None:
        return None

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

    def prespec_status_fields(
        self, session: Any, notice_ids: Sequence[int]
    ) -> Mapping[int, Mapping[str, Any]]:
        return {}


@dataclass(frozen=True)
class _OwnedProvider:
    """projection 자리를 채운 제공자와 그것을 등록한 owner.

    lifecycle은 `owner`를 **불투명한 키**로만 쓴다. 값을 비교해 "같은 등록자인가"만
    묻고 그 문자열의 의미(어느 모듈인가)는 해석하지 않는다.
    """

    owner: str
    provider: Any


def _checked_owner(owner: str) -> str:
    """등록자 키의 최소 형식 검사. 값의 **의미**는 보지 않는다."""

    if not isinstance(owner, str) or not owner:
        raise ValueError("확장점 등록에는 비어 있지 않은 owner 문자열이 필요하다")
    return owner


def _claim_slot(
    current: _OwnedProvider | None, owner: str, provider: Any, label: str
) -> _OwnedProvider:
    """projection 자리 하나를 채운다.

    같은 owner의 재등록은 제자리 교체다(`create_app()`을 두 번 불러도 예외가 없다).
    다른 owner가 이미 찬 자리를 채우려는 것은 조립 오류이므로 `RuntimeError`다.
    """

    owner = _checked_owner(owner)
    if current is not None and current.owner != owner:
        raise RuntimeError(
            f"{label} 제공자가 이미 등록됐다: {current.owner!r}가 채운 자리를 "
            f"{owner!r}가 채우려 한다"
        )
    return _OwnedProvider(owner, provider)


@dataclass
class ExtensionRegistry:
    """프로세스 전역 단일 확장점 registry.

    lifecycle은 여기에 무엇이 있는지만 본다. 제공자가 없어도 projection 접근자는
    항상 객체를 돌려주므로 호출부가 `None` 분기를 하지 않는다. 필터·정렬을 422로
    거절해야 하는 자리만 `*_supported` 술어를 본다.

    등록은 **소유 모듈(owner)** 단위다. `owner`는 lifecycle에게 불투명한 문자열
    키일 뿐이며 lifecycle은 그 값의 의미를 해석하지 않는다 — 어느 모듈이
    등록했는지 알 필요가 없고, 같은 등록자를 알아보기만 하면 된다.

    - 같은 owner가 같은 자리에 다시 등록하면 **제자리 교체**다(idempotent).
      `create_app()`을 한 프로세스에서 두 번 불러도 예외가 없고 hook이 두 번
      실행되지 않는다.
    - 다른 owner가 이미 찬 projection 자리를 채우려 하면 `RuntimeError`다. 그것이
      "제공자가 조용히 교체되지 않는다"는 원래 보장의 실체다.
    - hook은 (종류, owner)로 키를 잡으므로 여러 모듈이 같은 종류를 등록하는 것은
      그대로 허용이고, 실행 순서는 지금처럼 **처음 등록된 순서**(=
      `BIDOPS_MODULES`가 준 순서)다. 재등록은 순서를 바꾸지 않는다.
    """

    _judgment: _OwnedProvider | None = None
    _overview: _OwnedProvider | None = None
    _run_ingest_hooks: dict[str, RunIngestHook] = field(default_factory=dict)
    _tracking_hooks: dict[str, TrackingDecisionHook] = field(default_factory=dict)
    _effective_grade_hooks: dict[str, EffectiveGradeChangedHook] = field(default_factory=dict)

    _absent_judgment: Any = field(default_factory=_AbsentJudgmentProjection, repr=False)
    _absent_overview: Any = field(default_factory=_AbsentOverviewDocumentProjection, repr=False)

    # --- 등록 (조립 계층이 앱 조립 시점에 호출한다) ---
    def register_judgment_projection(
        self, projection: JudgmentProjection, *, owner: str
    ) -> None:
        self._judgment = _claim_slot(self._judgment, owner, projection, "판정 projection")

    def register_overview_document_projection(
        self, projection: OverviewDocumentProjection, *, owner: str
    ) -> None:
        self._overview = _claim_slot(self._overview, owner, projection, "개요·문서 projection")

    def register_run_ingest_hook(self, hook: RunIngestHook, *, owner: str) -> None:
        # `dict`는 이미 있는 키에 다시 넣어도 **자리를 옮기지 않는다.** 그래서
        # 재등록이 실행 순서를 바꾸지 않는다.
        self._run_ingest_hooks[_checked_owner(owner)] = hook

    def register_tracking_decision_hook(self, hook: TrackingDecisionHook, *, owner: str) -> None:
        self._tracking_hooks[_checked_owner(owner)] = hook

    def register_effective_grade_changed_hook(
        self, hook: EffectiveGradeChangedHook, *, owner: str
    ) -> None:
        self._effective_grade_hooks[_checked_owner(owner)] = hook

    # --- 조회 (lifecycle이 호출한다) ---
    @property
    def judgment_projection(self) -> JudgmentProjection:
        return self._judgment.provider if self._judgment is not None else self._absent_judgment

    @property
    def judgment_filters_supported(self) -> bool:
        """`grade`·`readiness`·`focus` 필터와 `sort=grade`를 받아도 되는가.

        제공자가 없으면 그 query는 422다(§6.1). 이것은 모듈 이름이 아니라 능력을
        묻는 술어다.
        """

        return self._judgment is not None

    @property
    def overview_document_projection(self) -> OverviewDocumentProjection:
        return self._overview.provider if self._overview is not None else self._absent_overview

    @property
    def overview_filters_supported(self) -> bool:
        """개요 상태 필터를 받아도 되는가. 제공자가 없으면 422다(§6.1)."""

        return self._overview is not None

    # --- hook 실행 (등록 순서대로, 호출자가 넘긴 session에서 동기적으로) ---
    def claim_run_directory(self, directory: Path) -> RunDirectoryClaim | None:
        """등록된 hook에 디렉터리를 보여 준다. 아무도 답하지 않으면 `None`."""

        for hook in self._run_ingest_hooks.values():
            claim = hook.inspect_run_directory(directory)
            if claim is not None:
                return claim
        return None

    def run_ingested(
        self,
        session: Any,
        run_id: str,
        directory: Path,
        *,
        reports_root: Path | None = None,
    ) -> RunIngestCounts:
        """등록 순서대로 실행하고 건수를 합친다. hook이 없으면 모두 0이다."""

        counts = RunIngestCounts()
        for hook in self._run_ingest_hooks.values():
            counts = counts.merged_with(
                hook.run_ingested(session, run_id, directory, reports_root=reports_root)
            )
        return counts

    def tracking_decision_changed(self, session: Any, opportunity_id: Any) -> None:
        """등록 순서대로 실행한다. hook이 없으면 아무 일도 하지 않는다."""

        for hook in self._tracking_hooks.values():
            hook.tracking_decision_changed(session, opportunity_id)

    def effective_grade_changed(self, session: Any, notice_ids: Sequence[int]) -> None:
        """등록 순서대로 실행한다. hook이 없으면 아무 일도 하지 않는다 (§6.2).

        빈 `notice_ids`도 그대로 넘긴다 — "0건 일치"와 "제한하지 않음"을 섞지
        않는 것과 같은 이유로, 대상이 없다는 사실은 구현이 판단한다.
        """

        for hook in self._effective_grade_hooks.values():
            hook.effective_grade_changed(session, notice_ids)

    @property
    def run_ingest_hook_count(self) -> int:
        return len(self._run_ingest_hooks)

    @property
    def tracking_decision_hook_count(self) -> int:
        return len(self._tracking_hooks)

    @property
    def effective_grade_changed_hook_count(self) -> int:
        return len(self._effective_grade_hooks)


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


def restore_extension_registry(registry: ExtensionRegistry) -> ExtensionRegistry:
    """`reset_extension_registry` 이전의 registry 객체를 되돌려 놓는다.

    조립 계층(`main.py`)은 앱 객체를 만들 때 **그 시점의** 전역 registry에 등록한다.
    테스트가 reset으로 새 객체를 만들고 그대로 두면, 같은 프로세스에서 뒤에 도는
    API 테스트는 등록이 사라진 빈 registry를 보게 된다. 그래서 reset을 쓰는
    fixture는 끝날 때 원래 객체를 이 함수로 되돌린다. 운영 경로는 호출하지 않는다.
    """

    global _REGISTRY
    _REGISTRY = registry
    return _REGISTRY
