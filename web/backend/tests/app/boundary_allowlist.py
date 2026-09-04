"""도입 시점(T2)의 경계 위반 허용 목록.

항목은 `(파일, 위반 종류, 대상)`이다. 목록에 없는 새 위반은 즉시 실패하고,
목록에 있는데 더 이상 위반이 아닌 항목이 남아 있어도 실패한다. 그래서 목록은
이주 task마다 줄어드는 방향으로만 바뀐다.
"""

from __future__ import annotations


#: 검사 1 — 명세 §4 허용 표에 없는 방향의 모듈 간 import.
#:
#: `app/models.py`·`app/schemas/__init__.py`가 대상일 때는 `모듈:이름` 형태로,
#: 그 밖에는 대상 모듈 경로로 적는다. 이주 task마다 이 목록은 줄어들기만 한다.
#: T8 1단계가 비웠다. 남아 있던 일곱 건은 모두 `app/main.py`·`app/runtime.py`가
#: lifecycle 내부 경로(routers/*, services/pipeline)를 직접 들던 자리였다. 네
#: 모듈이 공개 표면(`__init__`)에 router 인스턴스와 `build_runtime`을 올리면서
#: 조립 계층은 모듈 내부 경로를 하나도 들지 않는다.
CROSS_MODULE_IMPORT_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset()

#: 검사 2 — router 안의 직접 ORM 접근.
#:
#: 명세 §8이 이번 이주의 범위 밖으로 둔 항목이라 마지막 단계까지 남는다.
#: 새 위반만 막는다.
ROUTER_ORM_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("app/deep_review/routers/attachments.py", "router_orm_access", "sqlalchemy.select"),
        ("app/lifecycle/routers/common.py", "router_orm_access", "sqlalchemy.select"),
        ("app/deep_review/routers/deep_reviews.py", "router_orm_access", "sqlalchemy.select"),
        ("app/deep_review/routers/document_bundles.py", "router_orm_access", "sqlalchemy.select"),
        ("app/lifecycle/routers/notices.py", "router_orm_access", "sqlalchemy.select"),
        ("app/lifecycle/routers/opportunities.py", "router_orm_access", "sqlalchemy.select"),
        ("app/screening/routers/policies.py", "router_orm_access", "sqlalchemy.select"),
        ("app/lifecycle/routers/portals.py", "router_orm_access", "sqlalchemy.select"),
        ("app/lifecycle/routers/pre_specs.py", "router_orm_access", "Session.execute"),
        ("app/lifecycle/routers/pre_specs.py", "router_orm_access", "sqlalchemy.select"),
        ("app/screening/routers/profile.py", "router_orm_access", "sqlalchemy.select"),
        ("app/screening/routers/quality_gates.py", "router_orm_access", "Session.execute"),
        ("app/screening/routers/quality_gates.py", "router_orm_access", "sqlalchemy.select"),
        ("app/deep_review/routers/reports.py", "router_orm_access", "sqlalchemy.select"),
        ("app/screening/routers/reviews.py", "router_orm_access", "sqlalchemy.select"),
        ("app/lifecycle/routers/runs.py", "router_orm_access", "sqlalchemy.select"),
        ("app/screening/routers/schedule.py", "router_orm_access", "sqlalchemy.select"),
        ("app/screening/routers/screening.py", "router_orm_access", "sqlalchemy.select"),
    }
)

#: 검사 3 — `schemas`가 `models`·`services`를 import하는 자리.
#:
#: T7 2단계가 비웠다. `app/schemas/__init__.py`는 `PROFILE_PARSE_ERROR_CODES`를
#: `app.services.profile`에서 받고 있었는데, 그 상수의 정의는 이미 T3가
#: `app.core.company_profile`로 옮겨 둔 것이라 재수출을 거치지 않고 core에서
#: 직접 받도록 바꿨다. 값과 동작은 같다.
SCHEMA_IMPORT_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset()

#: 검사 4 — 다른 모듈 모델로 향하는 lifecycle 모델의 `relationship`.
LIFECYCLE_RELATIONSHIP_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset()

#: 검사 5 — screening·deep_review가 lifecycle 테이블에 직접 쓰거나 잠그는 자리.
#:
#: 최종 검토가 "§4의 네 세부 규칙 중 쓰기·잠금 한 줄만 어떤 검사도 덮지 않는다"를
#: 지적해 검사를 새로 넣었다. 넣는 시점의 실측 위반은 17건이었고(screening 3,
#: deep_review 14) 전부 `lifecycle.lock_notice`·`lock_attachment`·
#: `lock_active_attachments`·`delete_run`·`seed_default_portals`로 옮겨 **0이 됐다.**
#: 다른 목록과 같은 계약이다 — 목록에 없는 새 위반은 즉시 실패한다.
LIFECYCLE_TABLE_WRITE_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset()

#: 검사 6 — startup 경로의 조립 파일이 받는 상태 변경·모델 호출 이름.
#:
#: 검사를 넣는 시점의 실측 위반은 **0건**이다. 조립 계층 → 모듈 공개 이름은 허용
#: 방향이라 검사 1~5 어느 것도 이 자리를 덮지 않았고, 그래서 지금은 깨끗해도
#: 다음 변경이 조용히 경계를 넘을 수 있었다. 대상 파일과 금지 이름은
#: `boundary_map.STARTUP_FILES`·`STARTUP_FORBIDDEN_NAMES`에 데이터로 있다.
#: 다른 목록과 같은 계약이다 — 목록에 없는 새 위반은 즉시 실패한다.
ASSEMBLY_STARTUP_IMPORT_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset()


#: 허용 목록 크기의 상한. 이주 task는 이 값을 **내리기만** 한다.
#: T2 검토에서 한 번 다시 세웠다: deep_review → screening을 seam 이름만 허용하도록
#: 조이면서 §4 위반 3건이 새로 잡혔고(document_bundles→Judgment·Review,
#: input_versions→Review), 동시에 §5.2가 다른 모듈로 옮기기로 열거한 이름들을
#: 이름 단위로 풀면서 거짓 위반 12건이 빠져 66 → 57이 됐다.
#: 위 목록은 실제 위반과 정확히 같아야 하므로(stale 항목도 실패), 이 상한은
#: "새 위반을 허용 목록에 추가해 정당화하는" 경로를 추가로 막는다.
#: T5a와 T5b가 판정·심층 검토 접근을 확장점·seam·공개 함수로 뒤집고, 병합 뒤
#: 심층 검토가 판정을 읽던 세 자리를 선별 seam으로 바꾸면서 58 → 7이 됐다.
#: lifecycle relationship 9건은 전부 사라졌다. 남은 7건은 조립 계층이 아직 모듈
#: 내부를 직접 들고 있는 자리이며 T7·T8이 없앤다.
#: T7 2단계는 screening 폴더 이주만 했으므로 router 18건은 경로만 바뀌었고,
#: schemas → services 1건은 실제로 사라져 0이 됐다.
#: T8 1단계가 모듈 공개 표면을 만들면서 조립 계층의 마지막 7건이 사라져 0이 됐다.
BASELINE_SIZES: dict[str, int] = {
    "cross_module_import": 0,
    "router_orm_access": 18,
    "schema_imports_model_or_service": 0,
    "lifecycle_relationship": 0,
    "lifecycle_table_write": 0,
    "assembly_startup_import": 0,
}
