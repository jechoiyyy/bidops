#!/usr/bin/env python3
"""Create a new immutable methods config for the approved private Qwen vLLM."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
import sys

from common import ExperimentError, is_sha256, load_json, sha256_file, write_json_new


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-config", required=True, type=Path)
    parser.add_argument("--prompt-file", required=True, type=Path)
    parser.add_argument("--model-name", default="qwen3.8:27b")
    parser.add_argument("--model-revision", required=True)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--batch-size", type=int, default=25)
    args = parser.parse_args()
    try:
        if not is_sha256(args.model_revision):
            raise ExperimentError(
                "model_revision_unfixed",
                "서버 운영자가 제공한 64자 model artifact digest가 필요합니다",
            )
        if args.batch_size < 1:
            raise ExperimentError("invalid_batch_size", "batch-size는 1 이상이어야 합니다")
        prompt_path = args.prompt_file.resolve()
        if prompt_path.is_symlink() or not prompt_path.is_file():
            raise ExperimentError("prompt_invalid", "prompt는 symlink가 아닌 일반 파일이어야 합니다")
        config = copy.deepcopy(load_json(args.base_config.resolve()))
        qwen = config["methods"]["qwen"]
        qwen.update(
            {
                "method_version": "vllm-qwen-order-plan-batch-nonthinking-v4",
                "model_name": args.model_name,
                "model_revision": args.model_revision,
                "prompt_id": "order-plan-batch-relevance-v3",
                "prompt_sha256": sha256_file(prompt_path),
                "api_style": "openai_compatible",
                "base_url_env": "BIDOPS_QWEN_BASE_URL",
                "revision_env": "BIDOPS_QWEN_MODEL_REVISION",
                "bind_interface_env": "BIDOPS_QWEN_BIND_INTERFACE",
                "allowed_bind_interfaces": ["eth1"],
                "allowed_hosts": ["192.168.0.139"],
                "timeout_seconds": 300,
                "batch_size": args.batch_size,
                "max_output_tokens": 8192,
                "chat_template_kwargs": {"enable_thinking": False},
            }
        )
        write_json_new(args.out.resolve(), config)
        print(f"methods_config={args.out} prompt_sha256={qwen['prompt_sha256']}")
        return 0
    except (ExperimentError, KeyError) as exc:
        code = exc.code if isinstance(exc, ExperimentError) else "methods_config_invalid"
        print(f"status=failed error_code={code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
