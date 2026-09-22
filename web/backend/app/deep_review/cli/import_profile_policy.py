"""Import immutable company profile and analysis-policy versions.

The command intentionally never edits active environment variables.  An
operator must deploy the returned immutable IDs after quality measurements
have been recorded and verified.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ...core.db import SessionLocal, init_db
from ..services.input_versions import (
    CANONICAL_POLICY_FILE,
    PROFILE_SOURCE_FILE,
    InputVersionError,
    import_policy_version,
    import_profile_version,
    load_canonical_policy,
)


_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def import_profile_policy(
    session: Session,
    *,
    profile_source: Path | None = None,
    policy_source: Path | None = None,
    actor: str | None = None,
    label: str = "analysis-policy-lean-v1",
    expected_policy_sha256: str | None = None,
    sample_hash: str | None = None,
    required_item_recall: float | None = None,
    human_agreement: float | None = None,
    unsupported_false_positive_rate: float | None = None,
    repair_profile_source: bool = False,
) -> dict[str, Any]:
    quality_values = (
        sample_hash,
        required_item_recall,
        human_agreement,
        unsupported_false_positive_rate,
    )
    if any(value is not None for value in quality_values):
        if expected_policy_sha256 is None or not _HEX64.fullmatch(expected_policy_sha256):
            raise InputVersionError("invalid_request", "measured policy import에는 expected policy sha256이 필요합니다")
    if expected_policy_sha256 is not None:
        if not _HEX64.fullmatch(expected_policy_sha256):
            raise InputVersionError("invalid_request", "expected policy sha256 형식이 올바르지 않습니다")
        _policy_payload, _canonical_bytes, actual_policy_sha256 = load_canonical_policy(policy_source)
        if actual_policy_sha256 != expected_policy_sha256:
            raise InputVersionError("policy_hash_mismatch", "측정한 policy와 import 대상 policy hash가 다릅니다")
    profile = import_profile_version(session, profile_source, created_by_name=actor, label="company-profile", repair_missing_source=repair_profile_source)
    policy = import_policy_version(
        session, policy_source, created_by_name=actor, label=label,
        sample_hash=sample_hash, required_item_recall=required_item_recall,
        human_agreement=human_agreement, unsupported_false_positive_rate=unsupported_false_positive_rate,
    )
    if expected_policy_sha256 is not None and policy.policy_sha256 != expected_policy_sha256:
        session.rollback()
        raise InputVersionError("policy_hash_mismatch", "측정한 policy와 import 대상 policy hash가 다릅니다")
    session.commit()
    return {
        "profile_version_id": str(profile.id), "profile_sha256": profile.profile_sha256,
        "policy_version_id": str(policy.id), "policy_sha256": policy.policy_sha256,
        "active_configuration_changed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.deep_review.cli import-profile-policy",
        description="Import immutable BidOps deep-review profile/policy versions",
    )
    parser.add_argument("--profile", type=Path, default=None, help=f"profile source (default: {PROFILE_SOURCE_FILE})")
    parser.add_argument("--policy", type=Path, default=None, help="canonical policy source")
    parser.add_argument("--actor", required=True, help="operator name")
    parser.add_argument("--label", default="analysis-policy-lean-v1")
    parser.add_argument("--expected-policy-sha256")
    parser.add_argument("--repair-profile-source", action="store_true", help="reconnect identical approved profile bytes when a historical object version is unavailable; append an audited location")
    parser.add_argument("--sample-hash")
    parser.add_argument("--required-item-recall", type=float)
    parser.add_argument("--human-agreement", type=float)
    parser.add_argument("--unsupported-false-positive-rate", type=float)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        init_db()
        with SessionLocal() as session:
            result = import_profile_policy(
                session, profile_source=args.profile, policy_source=args.policy, actor=args.actor,
                label=args.label, expected_policy_sha256=args.expected_policy_sha256,
                sample_hash=args.sample_hash,
                required_item_recall=args.required_item_recall, human_agreement=args.human_agreement,
                unsupported_false_positive_rate=args.unsupported_false_positive_rate,
                repair_profile_source=args.repair_profile_source,
            )
            import json
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except InputVersionError as error:
        print(f"import failed: {error.code}")
        return 2
    return 0



__all__ = ["build_parser", "import_profile_policy", "main"]


if __name__ == "__main__":  # pragma: no cover
    # T8 2단계가 이 파일의 직접 실행 경로를 없앴다. 호환 shim을 두지 않으므로
    # 옛 명령은 동작하지 않는다. 다만 그냥 두면 `__main__` 블록이 없는 모듈이
    # 아무 일도 하지 않고 종료 코드 0을 내서, 옛 기록을 따라 실행한 운영자가
    # 성공으로 오인한다. mutating 명령이 조용히 건너뛰지 않도록 fail-closed로 막는다.
    raise SystemExit("이 명령은 `python -m app.deep_review.cli import-profile-policy <인자>`로 실행한다")
