"""Import immutable company profile and analysis-policy versions.

The command intentionally never edits active environment variables.  An
operator must deploy the returned immutable IDs after quality measurements
have been recorded and verified.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..db import SessionLocal, init_db
from ..services.input_versions import (
    CANONICAL_POLICY_FILE,
    PROFILE_SOURCE_FILE,
    InputVersionError,
    import_policy_version,
    import_profile_version,
)


def import_profile_policy(
    session: Session,
    *,
    profile_source: Path | None = None,
    policy_source: Path | None = None,
    actor: str | None = None,
    label: str = "analysis-policy-lean-v1",
    sample_hash: str | None = None,
    required_item_recall: float | None = None,
    human_agreement: float | None = None,
    unsupported_false_positive_rate: float | None = None,
) -> dict[str, Any]:
    profile = import_profile_version(session, profile_source, created_by_name=actor, label="company-profile")
    policy = import_policy_version(
        session, policy_source, created_by_name=actor, label=label,
        sample_hash=sample_hash, required_item_recall=required_item_recall,
        human_agreement=human_agreement, unsupported_false_positive_rate=unsupported_false_positive_rate,
    )
    session.commit()
    return {
        "profile_version_id": str(profile.id), "profile_sha256": profile.profile_sha256,
        "policy_version_id": str(policy.id), "policy_sha256": policy.policy_sha256,
        "active_configuration_changed": False,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Import immutable BidOps deep-review profile/policy versions")
    parser.add_argument("--profile", type=Path, default=None, help=f"profile source (default: {PROFILE_SOURCE_FILE})")
    parser.add_argument("--policy", type=Path, default=None, help="canonical policy source")
    parser.add_argument("--actor", required=True, help="operator name")
    parser.add_argument("--label", default="analysis-policy-lean-v1")
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
                label=args.label, sample_hash=args.sample_hash,
                required_item_recall=args.required_item_recall, human_agreement=args.human_agreement,
                unsupported_false_positive_rate=args.unsupported_false_positive_rate,
            )
            import json
            print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    except InputVersionError as error:
        print(f"import failed: {error.code}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


__all__ = ["build_parser", "import_profile_policy", "main"]
