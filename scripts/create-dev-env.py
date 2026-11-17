#!/usr/bin/env python3
"""Create isolated local credentials once; never read or copy production secrets."""
from __future__ import annotations

import os
from pathlib import Path
import secrets


def main() -> None:
    mode = os.environ.get("BIDOPS_ENV", "dev")
    if mode not in {"dev", "mock"}:
        raise SystemExit("Local credential generation only supports BIDOPS_ENV=dev or mock")
    path = Path(__file__).resolve().parents[1] / "env" / f"{mode}.env"
    values = {}
    for role in ("OWNER", "MIGRATE", "APP", "WORKER", "RO_BACKUP"):
        values[f"BIDOPS_{role}_PASSWORD"] = secrets.token_hex(24)
    values["BIDOPS_MINIO_ROOT_USER"] = secrets.token_hex(10)
    values["BIDOPS_MINIO_ROOT_PASSWORD"] = secrets.token_hex(24)
    for bucket in ("SOURCE", "STRUCTURE", "STRUCTURE_READ", "QUARANTINE", "MODEL_RESPONSE", "PROPOSAL_PDF"):
        values[f"BIDOPS_{bucket}_ACCESS_KEY"] = secrets.token_hex(10)
        values[f"BIDOPS_{bucket}_SECRET_KEY"] = secrets.token_hex(24)
    values["BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY"] = secrets.token_hex(32)
    values["BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY_REF"] = f"{mode}-local-v1"
    body = "# Generated local credentials; gitignored. Do not reuse for production.\n"
    body += "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        print(f"Preserved existing {path.relative_to(path.parents[1])}")
        return
    with os.fdopen(fd, "w") as stream:
        stream.write(body)
    print(f"Created env/{mode}.env (0600); no services started")


if __name__ == "__main__":
    main()
