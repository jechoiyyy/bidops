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
CROSS_MODULE_IMPORT_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        # T5a가 판정 projection·회차 적재 hook·seam으로 lifecycle → screening 접근을
        # 모두 끊었다. ingest/loader.py, routers/{common,notices,runs}.py,
        # services/metrics.py의 판정·리뷰 참조와 lifecycle 모델의 판정 방향
        # relationship 일곱 개가 함께 사라졌다.
        #
        # T4가 "조립 계층 → lifecycle은 공개 이름만"을 켜면서 새로 드러난 자리다
        # (규칙을 켜기 전에는 검사 대상이 아니었으므로 목록이 늘었다). lifecycle
        # router 파일들은 T7이 app/lifecycle/routers/로 옮기고 T8이 BIDOPS_MODULES에
        # 따라 등록하면서, PipelineService는 T8이 모듈 runtime으로 옮기면서 사라진다.
        # lifecycle/__init__.py에서 지금 router를 재공개하지 않는 이유: T5a·T5b가
        # router 안에서 확장점 registry를 쓰게 되면 app.lifecycle → app.routers →
        # app.lifecycle 순환 import가 된다.
        ("app/main.py", "cross_module_import", "app.routers.metrics:router"),
        ("app/main.py", "cross_module_import", "app.routers.notices:router"),
        ("app/main.py", "cross_module_import", "app.routers.opportunities:router"),
        ("app/main.py", "cross_module_import", "app.routers.portals:router"),
        ("app/main.py", "cross_module_import", "app.routers.pre_specs:router"),
        ("app/main.py", "cross_module_import", "app.routers.runs:router"),
        ("app/runtime.py", "cross_module_import", "app.services.pipeline:PipelineService"),
    }
)

#: 검사 2 — router 안의 직접 ORM 접근.
#:
#: 명세 §8이 이번 이주의 범위 밖으로 둔 항목이라 마지막 단계까지 남는다.
#: 새 위반만 막는다.
ROUTER_ORM_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("app/routers/attachments.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/common.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/deep_reviews.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/document_bundles.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/notices.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/opportunities.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/policies.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/portals.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/pre_specs.py", "router_orm_access", "Session.execute"),
        ("app/routers/pre_specs.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/profile.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/quality_gates.py", "router_orm_access", "Session.execute"),
        ("app/routers/quality_gates.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/reports.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/reviews.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/runs.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/schedule.py", "router_orm_access", "sqlalchemy.select"),
        ("app/routers/screening.py", "router_orm_access", "sqlalchemy.select"),
    }
)

#: 검사 3 — `schemas`가 `models`·`services`를 import하는 자리.
SCHEMA_IMPORT_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("app/schemas/__init__.py", "schema_imports_model_or_service", "app.services.profile"),
    }
)

#: 검사 4 — 다른 모듈 모델로 향하는 lifecycle 모델의 `relationship`.
LIFECYCLE_RELATIONSHIP_ALLOWLIST: frozenset[tuple[str, str, str]] = frozenset()


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
BASELINE_SIZES: dict[str, int] = {
    "cross_module_import": 7,
    "router_orm_access": 18,
    "schema_imports_model_or_service": 1,
    "lifecycle_relationship": 0,
}
