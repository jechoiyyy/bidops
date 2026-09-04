"""C-2(발주계획 선별) 전용 회차 디렉터리 픽스처.

`tests/` 루트 헬퍼다. lifecycle·screening·app 어느 폴더의 테스트든 같은 산출물
집합으로 "C-2 전용 디렉터리"를 만들 수 있게 한 곳에 둔다. 정책·binding 파일은
`experiments/order-plan-screening/config/`의 실제 파일을 그대로 읽는다 — 운영
적재기가 같은 경로를 런타임 의존으로 갖고 있으므로 픽스처도 그 계약을 따른다.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4


def write_c2_json(path: Path, value: dict) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def write_c2_fixture(root: Path, *, failed: bool = False) -> tuple[Path, str]:
    run_dir = root / "runs" / ("c2-failed" if failed else "c2-success")
    run_dir.mkdir(parents=True)
    plan_id = "R26DD20999999"
    source_run_id = "c2-loader-source-" + ("failed" if failed else "success")
    execution_id = str(uuid4())
    created_at = "2026-09-01T00:00:00+00:00"
    repository_root = Path(__file__).resolve().parents[3]
    policy_path = repository_root / "experiments/order-plan-screening/config/order-plan-screening-policy.v1.json"
    binding_path = repository_root / "experiments/order-plan-screening/config/order-plan-screening-phase0-binding.v1.json"
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    policy_sha256 = hashlib.sha256(policy_path.read_bytes()).hexdigest()
    binding_sha256 = hashlib.sha256(binding_path.read_bytes()).hexdigest()
    population = [{"plan_id": plan_id, "title": "AI 데이터 플랫폼"}]
    population_sha256 = hashlib.sha256(
        json.dumps(population, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    source = {
        "schema_version": "bidops.collected-order-plans.v1",
        "generated_at": created_at,
        "source_window": {"from": "2026-08-25", "to": "2026-08-26", "timezone": "Asia/Seoul"},
        "counts": {"total": 1},
        "warnings": [],
        "order_plans": [{"order_plan_unty_no": plan_id, "title": "AI 데이터 플랫폼"}],
    }
    source_sha256 = write_c2_json(run_dir / "collected-order-plans.json", source)
    input_value = {
        "schema_version": "bidops.order-plan-screening-input.v1",
        "producer": "order-plan-screening-orchestrator",
        "consumer": "order-plan-screening-worker",
        "execution_id": execution_id,
        "source_run_id": source_run_id,
        "source_artifact": {
            "name": "collected-order-plans.json",
            "schema_version": "bidops.collected-order-plans.v1",
            "sha256": source_sha256,
        },
        "population_count": 1,
        "population_sha256": population_sha256,
        "policy": {"version": policy["policy_version"], "sha256": policy_sha256},
        "stage1_binding": {
            "version": "bm25-char-title-capability-v1",
            "sha256": binding["stage1_binding"]["sha256"],
        },
        "stage2_binding": {"version": binding["binding_version"], "sha256": binding_sha256},
        "items": population,
        "status": "frozen",
        "created_at": created_at,
    }
    input_sha256 = write_c2_json(run_dir / "screening-input.json", input_value)
    ranking_value = {
        "schema_version": "bidops.order-plan-screening-ranking.v1",
        "producer": "order-plan-screening-bm25",
        "consumer": "order-plan-screening-merge",
        "execution_id": execution_id,
        "source_run_id": source_run_id,
        "input_artifact_sha256": input_sha256,
        "policy_version": policy["policy_version"],
        "policy_sha256": policy_sha256,
        "status": "성공",
        "population_count": 1,
        "selected_count": 1,
        "filtered_out_count": 0,
        "items": [{
            "plan_id": plan_id,
            "rank": 1,
            "score": 1.0,
            "nearest_capability": "cap-ai",
            "stage1_status": "selected",
        }],
        "created_at": created_at,
    }
    ranking_sha256 = write_c2_json(run_dir / "screening-ranking.json", ranking_value)
    binding_value = {
        "model_name": binding["stage2_binding"]["model_name"],
        "model_digest": binding["stage2_binding"]["model_digest"],
        "prompt_version": binding["stage2_binding"]["prompt_version"],
        "prompt_sha256": binding["stage2_binding"]["prompt_sha256"],
        "company_profile_version": binding["stage2_binding"]["company_profile_version"],
        "company_profile_sha256": binding["stage2_binding"]["company_profile_sha256"],
        "generation_config_sha256": binding["stage2_binding"]["generation_config_sha256"],
    }
    decisions_value = {
        "schema_version": "bidops.order-plan-screening-decisions.v1",
        "producer": "order-plan-screening-qwen-worker",
        "consumer": "order-plan-screening-merge",
        "execution_id": execution_id,
        "source_run_id": source_run_id,
        "input_artifact_sha256": input_sha256,
        "ranking_artifact_sha256": ranking_sha256,
        "binding": binding_value,
        "status": "실패" if failed else "성공",
        "candidate_count": 1,
        "success_count": 0 if failed else 1,
        "failure_count": 1 if failed else 0,
        "batch_count": 1,
        "batches": [{
            "batch_id": "batch-001",
            "sequence": 1,
            "plan_ids": [plan_id],
            "attempt_count": 1,
            "status": "failed" if failed else "success",
        }],
        "items": [] if failed else [{
            "plan_id": plan_id,
            "batch_id": "batch-001",
            "attempt_no": 1,
            "relevance": "relevant",
            "score": 0.1,
            "reason": "bounded fixture decision",
        }],
        "created_at": created_at,
    }
    write_c2_json(run_dir / "screening-decisions.json", decisions_value)
    failures_value = {
        "schema_version": "bidops.order-plan-screening-failures.v1",
        "producer": "order-plan-screening-worker",
        "consumer": "order-plan-screening-review-and-merge",
        "execution_id": execution_id,
        "source_run_id": source_run_id,
        "status": "failed" if failed else "none",
        "failure_count": 1 if failed else 0,
        "failures": [] if not failed else [{
            "batch_id": "batch-001",
            "sequence": 1,
            "plan_ids": [plan_id],
            "attempt_count": 1,
            "max_attempts": 2,
            "failure_type": "timeout",
            "outcome": "failed",
            "status": "human_review_required",
            "error_code": "fixture_timeout",
        }],
        "created_at": created_at,
    }
    write_c2_json(run_dir / "screening-failures.json", failures_value)
    measurement = {
        "started_at": created_at,
        "finished_at": "2026-09-01T00:00:00.001000+00:00",
        "duration_ms": 1,
        "input_tokens": 1,
        "cached_input_tokens": 0,
        "output_tokens": 1,
        "total_tokens": 2,
    }
    telemetry_value = {
        "schema_version": "bidops.order-plan-screening-telemetry.v1",
        "producer": "order-plan-screening-worker",
        "consumer": "observability-and-merge",
        "execution_id": execution_id,
        "source_run_id": source_run_id,
        "status": "partial" if failed else "complete",
        "execution": measurement,
        "batches": [{
            "batch_id": "batch-001",
            "sequence": 1,
            "status": "failed" if failed else "success",
            "attempts": [{
                "attempt_no": 1,
                "status": "failed" if failed else "success",
                "started_at": created_at,
                "finished_at": "2026-09-01T00:00:00.001000+00:00",
                "measurement": measurement,
            }],
        }],
        "created_at": created_at,
    }
    write_c2_json(run_dir / "screening-telemetry.json", telemetry_value)
    result_value = {
        "schema_version": "bidops.order-plan-screening-result.v1",
        "producer": "order-plan-screening-merge",
        "consumer": "postgres-loader-and-review-api",
        "execution_id": execution_id,
        "source_run_id": source_run_id,
        "input_artifact_sha256": input_sha256,
        "policy_version": policy["policy_version"],
        "policy_sha256": policy_sha256,
        "status": "실패" if failed else "성공",
        "partial_artifact": failed,
        "counts": {
            "population": 1,
            "stage1_selected": 1,
            "stage1_filtered_out": 0,
            "stage1_failed": 0,
            "stage2_relevant": 0 if failed else 1,
            "stage2_not_relevant": 0,
            "stage2_uncertain": 0,
            "stage2_failed": 1 if failed else 0,
            "stage2_rejected": 0,
            "human_review_count": 1,
        },
        "items": [{
            "plan_id": plan_id,
            "stage1_status": "selected",
            "stage1_rank": 1,
            "stage1_score": 1.0,
            "nearest_capability": "cap-ai",
            "stage2_status": "failed" if failed else "success",
            "qwen_relevance": None if failed else "relevant",
            "qwen_score": None if failed else 0.1,
            "qwen_reason": None if failed else "bounded fixture decision",
            "batch_id": "batch-001",
            "attempt_no": 1,
            "failure_code": "fixture_timeout" if failed else None,
        }],
        "created_at": created_at,
    }
    write_c2_json(run_dir / "screening-results.json", result_value)
    return run_dir, source_run_id
