"""`python -m app.lifecycle.cli build-briefing`이 web과 같은 확장점 제공자를 본다 (RL-01).

브리핑 규칙은 회사 사실(deep_review)과 발주계획 후보(screening)를 확장점으로만 받는다.
pytest 프로세스는 conftest가 이미 형제 모듈을 들여 registry가 차 있으므로, `build_briefing`을
직접 부르는 검사는 "CLI 프로세스에는 등록이 없다"는 결함을 보지 못한다(engineering-notes
"단위 검사는 CLI 프로세스와 web 프로세스의 확장점 등록 차이를 보지 못한다"). 그래서 여기서는
실제 인터프리터를 새로 띄워 CLI를 돌리고, 그 SQLite 파일을 다시 열어 결과를 읽는다.

- 기본 모듈(셋 다): 실회사 확정 사실로 추천을 만들고 발주계획 제공자 부재 경고가 없다.
- `lifecycle,deep_review`: 회사 사실은 있으나 발주계획 제공자 부재 경고가 남는다.
- `lifecycle`: 회사 사실 제공자가 없어 `company_not_registered`(exit 1), 행 없음.

두 모듈 이상이 만나는 검사라 `tests/app/`에 둔다.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.core.db import init_db
from app.deep_review.services.company_knowledge import (
    activate_company_knowledge,
    import_company_knowledge,
)
from app.lifecycle.models import Briefing, BriefingItem
import app.main  # noqa: F401 - 네 모듈의 선언 테이블을 모두 등록한다
from tests.deep_review.test_company_knowledge import (  # noqa: F401 - autouse 객체 저장소 fixture
    _prepared_real,
    fictional_import_demo,
    object_store,
)
from tests.lifecycle.briefing_fixtures import World

BACKEND_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_KEYS = {
    "briefing_date", "status", "created", "item_count", "tracked_change_count", "excluded", "warnings", "slack",
}


def _seed(root: Path):
    """실회사(확정 사실 `pref:domain:01` 키워드 `공공`)를 활성화하고 후보 공고 하나를 심는다."""

    root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{root / 'cli.db'}")
    init_db(engine)
    with Session(engine, expire_on_commit=False) as session:
        with session.begin():
            imported = import_company_knowledge(session, _prepared_real(), actor="등록 담당자")
            activate_company_knowledge(
                session,
                company_id=imported.company_id,
                graph_version_id=imported.graph_version_id,
                actor="활성 담당자",
            )
        world = World(session)
        world.collection_run()
        notice = world.notice("공공 데이터 플랫폼 구축")
        session.commit()
    engine.dispose()
    return imported.graph_version_id, notice.id


def _run_cli(root: Path, *args: str, modules: str | None = None) -> tuple[int, dict]:
    environment = dict(os.environ)
    for name in ("BIDOPS_ROOT", "BIDOPS_PROJECT_ROOT", "BIDOPS_DATA_DIR", "BIDOPS_MODULES"):
        environment.pop(name, None)
    # Slack 설정은 주지 않는다(기본 `BIDOPS_SLACK_ENABLED=false`). 전송 경로는
    # `test_slack_transport.py`가 127.0.0.1 가짜 Slack으로 본다.
    for name in [key for key in environment if key.startswith("BIDOPS_SLACK_")]:
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
        [sys.executable, "-m", "app.lifecycle.cli", "build-briefing", *args, "--json"],
        cwd=BACKEND_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        timeout=600,
    )
    assert "Traceback" not in completed.stderr, completed.stderr
    lines = completed.stdout.strip().splitlines()
    assert len(lines) == 1, completed.stdout
    output = json.loads(lines[0])
    assert set(output) == OUTPUT_KEYS
    return completed.returncode, output


def _rows(root: Path) -> tuple[list[Briefing], int]:
    engine = create_engine(f"sqlite:///{root / 'cli.db'}")
    try:
        with Session(engine) as session:
            return session.scalars(select(Briefing)).all(), int(session.scalar(select(func.count(BriefingItem.id))))
    finally:
        engine.dispose()


def test_cli_with_all_modules_uses_the_real_company_facts_and_order_plan_provider(tmp_path) -> None:
    root = tmp_path / "all"
    graph_version_id, _notice_id = _seed(root)

    code, output = _run_cli(root, "--date", "2026-10-16")

    assert code == 0, output
    assert output == {
        "briefing_date": "2026-10-16",
        "status": "generated",
        "created": True,
        "item_count": 1,
        "tracked_change_count": 0,
        "excluded": {
            "hardware": 0, "election": 0, "design_only": 0, "staffing_only": 0, "region": 0, "amount_floor": 0,
        },
        "warnings": [],
        "slack": {"sent": False, "message_ts": [], "skipped_reason": "not_requested"},
    }
    briefings, items = _rows(root)
    assert [row.graph_version_id for row in briefings] == [graph_version_id]
    assert items == 1

    again_code, again = _run_cli(root, "--date", "2026-10-16", "--send")
    assert again_code == 0
    assert (again["created"], again["status"], again["item_count"]) == (False, "generated", 1)
    # `BIDOPS_SLACK_ENABLED` 기본값 false: 전송기가 호출 전에 막는다.
    assert again["slack"] == {"sent": False, "message_ts": [], "skipped_reason": "slack_disabled"}
    assert len(_rows(root)[0]) == 1


def test_cli_without_screening_records_the_missing_order_plan_provider(tmp_path) -> None:
    root = tmp_path / "no-screening"
    _seed(root)

    code, output = _run_cli(root, "--date", "2026-10-16", modules="lifecycle,deep_review")

    assert code == 0, output
    assert (output["status"], output["created"], output["warnings"]) == (
        "generated", True, ["order_plan_provider_absent"],
    )


def test_cli_without_the_company_facts_provider_fails_closed(tmp_path) -> None:
    root = tmp_path / "lifecycle-only"
    _seed(root)

    code, output = _run_cli(root, "--date", "2026-10-16", modules="lifecycle")

    assert code == 1
    assert (output["status"], output["created"], output["warnings"]) == (None, False, ["company_not_registered"])
    assert _rows(root) == ([], 0)


@pytest.mark.parametrize(
    "args, skipped",
    [(("--date", "2026-10-17"), "weekend"), (("--date", "2026-10-16", "--dry-run", "--send"), "dry_run")],
    ids=["weekend", "dry-run"],
)
def test_cli_weekend_and_dry_run_create_no_row(tmp_path, args, skipped) -> None:
    root = tmp_path / skipped
    _seed(root)

    code, output = _run_cli(root, *args)

    assert code == 0
    assert output["created"] is False
    assert output["slack"] == {"sent": False, "message_ts": [], "skipped_reason": skipped}
    assert output["status"] == (None if skipped == "weekend" else "generated")
    assert _rows(root) == ([], 0)
