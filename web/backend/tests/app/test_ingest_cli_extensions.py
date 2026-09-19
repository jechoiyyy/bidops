"""적재 CLI 프로세스가 web 프로세스와 같은 확장점을 등록한다.

두 모듈이 한 회차에서 만나는 검사라 `tests/app/`에 둔다(§5.4).

이 파일이 막는 회귀는 **프로세스 경계에서만 보인다**. `ingest_run`을 직접 부르는
단위 검사는 pytest가 이미 `app.screening`·`app.deep_review`를 import해 둔 덕에
전역 registry가 차 있는 상태로 돌고, 그래서 "CLI 프로세스에는 등록이 없다"는
사실을 하나도 보지 못했다. 그 공백으로 2026-09-19 운영에서 다음이 일어났다.

1. `python -m app.lifecycle.ingest.cli --run <id> --collection`이 hook 없이 돌아
   회차에 `judgment_ingest_skipped` 경고를 남긴다.
2. C-2 실행 생성은 source run에 ingest warning이 하나라도 있으면 `409
   source_run_incomplete`로 거부한다.
3. 일일 발주계획 트랙(CLI 적재 → `run-daily-c2.sh`)과 게이트 측정이 매번 멈춘다.

그래서 여기서는 **실제 인터프리터를 새로 띄워** CLI로 적재한 뒤, 그 SQLite 파일을
다시 열어 C-2 서비스의 source run 검사를 제품 코드 그대로 통과시킨다.

`tests/lifecycle/test_ingest_without_screening.py`의 의도(선별 모듈이 없는 배포에서는
경고가 남는다)는 그대로 지킨다 — 두 번째 검사가 `BIDOPS_MODULES=lifecycle`로 같은
CLI를 돌려 그 경고와 409 사유가 여전히 살아 있음을 확인한다.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[2]

RUN_ID = "order-plans-20260918-20260919"
WINDOW = {"from": "2026-09-18", "to": "2026-09-19", "timezone": "Asia/Seoul"}


def _plan(number: str, title: str) -> dict[str, object]:
    return {
        "order_plan_unty_no": number,
        "title": title,
        "agency_code": "1234567",
        "agency_name": "테스트 발주기관",
        "published_at": "2026-09-18T09:00:00+09:00",
        "contract_method": "제한경쟁",
        "bid_ntice_no_list": None,
        "sw_business_status": None,
        # 원본 hash는 수집기가 준다. C-2의 모집단 대조가 이 값을 그대로 쓴다.
        "source_sha256": hashlib.sha256(number.encode("utf-8")).hexdigest(),
        "raw_source": "raw/page-00001.json",
    }


PLANS = [
    _plan("R26DD20800001", "통합 행정 플랫폼 구축"),
    _plan("R26DD20800002", "AI 데이터 분석 시스템 구축"),
]


def _write_collection_run(root: Path) -> Path:
    """수집기가 내는 모양 그대로의 발주계획 1일 회차."""

    run_dir = root / "data" / "runs" / RUN_ID
    run_dir.mkdir(parents=True)
    (run_dir / "collected-order-plans.json").write_text(
        json.dumps(
            {
                "schema_version": "bidops.collected-order-plans.v1",
                "generated_at": "2026-09-19T00:00:00+00:00",
                "source_window": WINDOW,
                "metadata": {"complete": True},
                "counts": {"total": len(PLANS)},
                "warnings": [],
                "order_plans": PLANS,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return run_dir


def _run_cli(root: Path, *, modules: str | None = None) -> dict[str, object]:
    """새 인터프리터에서 운영과 같은 명령을 돌리고 stdout JSON을 돌려준다."""

    environment = dict(os.environ)
    for name in ("BIDOPS_ROOT", "BIDOPS_PROJECT_ROOT", "BIDOPS_DATA_DIR", "BIDOPS_MODULES"):
        environment.pop(name, None)
    environment.update(
        {
            "BIDOPS_ROOT": str(root),
            "BIDOPS_DATABASE_URL": f"sqlite:///{root / 'cli.db'}",
            # 격리 경계 밖에서는 SQLite 자체가 거부된다. 운영은 PostgreSQL이다.
            "BIDOPS_TEST_MODE": "1",
            "PYTHONPATH": str(BACKEND_ROOT),
        }
    )
    if modules is not None:
        environment["BIDOPS_MODULES"] = modules
    completed = subprocess.run(
        [sys.executable, "-m", "app.lifecycle.ingest.cli", "--run", RUN_ID, "--collection"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert completed.returncode == 0, (
        f"적재 CLI가 실패했다 (exit {completed.returncode}).\n"
        f"--- stdout ---\n{completed.stdout}\n--- stderr ---\n{completed.stderr}"
    )
    return json.loads(completed.stdout)


def _c2_service(root: Path):
    from app.core.config import Settings
    from app.screening.services.order_plan_screening import OrderPlanScreeningService

    return OrderPlanScreeningService(Settings(bidops_root=root, database_url="sqlite://"))


def _session(root: Path) -> Session:
    engine = create_engine(f"sqlite:///{root / 'cli.db'}")
    return Session(engine)


def test_cli_ingested_collection_run_passes_the_c2_source_run_gate(tmp_path):
    root = tmp_path / "project"
    _write_collection_run(root)

    result = _run_cli(root)

    # 1. CLI 자신이 보고하는 것: 경고 0건.
    assert result["warnings"] == [], result["warnings"]
    assert result["order_plans"] == len(PLANS)
    assert result["selection"]["order_plan"]["collected"] == len(PLANS)

    from app.lifecycle.models import IngestWarning, Run

    run_id = str(result["run_id"])
    with _session(root) as session:
        # 2. DB에도 그 회차 경고가 없다 (C-2가 실제로 보는 것).
        assert session.scalars(
            select(IngestWarning.code).where(IngestWarning.run_id == run_id)
        ).all() == []

        # 3. C-2 실행 생성의 source run 검사를 제품 코드 그대로 통과한다.
        run, source_path, source_bytes, population = _c2_service(root).require_complete_source_run(
            session, run_id
        )

    assert isinstance(run, Run) and run.id == run_id
    assert source_path.name == "collected-order-plans.json"
    assert source_bytes == source_path.read_bytes()
    assert [row["plan_id"] for row in population] == [plan["order_plan_unty_no"] for plan in PLANS]


def test_a_lifecycle_only_deployment_still_records_the_skipped_warning(tmp_path):
    """선별 모듈이 없는 배포의 계약은 그대로다 (`test_ingest_without_screening`).

    등록은 `BIDOPS_MODULES`가 고른 모듈만 한다. lifecycle만 고르면 판정 적재
    제공자가 없으므로 경고가 남고, C-2는 그 회차를 계속 거부해야 한다 — 이번
    수정이 경고 자체를 없앤 것이 아니라 **등록을 붙인 것**임을 고정한다.
    """

    from app.screening.services.order_plan_screening import OrderPlanScreeningError

    root = tmp_path / "project"
    _write_collection_run(root)

    result = _run_cli(root, modules="lifecycle")

    assert [item["code"] for item in result["warnings"]] == ["judgment_ingest_skipped"]

    run_id = str(result["run_id"])
    with _session(root) as session:
        with pytest.raises(OrderPlanScreeningError) as raised:
            _c2_service(root).require_complete_source_run(session, run_id)

    assert raised.value.code == "source_run_incomplete"
    # 구체 사유는 로그로만 나간다. 응답 message는 router가 고정 문구로 바꾼다.
    assert "judgment_ingest_skipped" in raised.value.message
