#!/usr/bin/env python3
"""Create and restore an unencrypted, self-contained BidOps transfer folder.

Requires Python 3.12+, Linux Docker Engine and Compose v2. No automatic cron
installation, migration, model call, source deletion, or Git publication.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tarfile
import time


SCHEMA = "bidops.transfer.v1"
ROOT = Path(__file__).resolve().parent.parent
INPUTS = ("data", "reports", "web/data", "experiments/order-plan-screening/review-inputs")
OFF_FLAGS = (
    "BIDOPS_SCHEDULER_ENABLED", "BIDOPS_OPENAI_ENABLED", "BIDOPS_C2_EXECUTION_ALLOWED",
    "BIDOPS_C2_DAILY_TRIGGER_ENABLED", "BIDOPS_G2B_ATTACHMENT_ENABLED",
    "BIDOPS_PRESPEC_OVERVIEW_ENABLED", "BIDOPS_PRESPEC_COMPANY_FIT_ENABLED",
    "BIDOPS_DEEP_REVIEW_AUTO_START_ENABLED", "BIDOPS_LUNA_DEEP_REVIEW_ENABLED",
)


def run(args, *, data=None, output=None):
    """Never echo command arguments or stderr: either can contain secrets."""
    result = subprocess.run(args, input=data, stdout=output or subprocess.PIPE,
                            stderr=subprocess.PIPE)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).name} failed (exit {result.returncode}); sensitive output suppressed")
    return result.stdout or b""


def docker(*args, **kwargs):
    return run(["docker", *map(str, args)], **kwargs)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_json(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def service(container):
    return container["Config"]["Labels"]["com.docker.compose.service"]


def inventory(project):
    ids = docker("ps", "-aq", "--filter", f"label=com.docker.compose.project={project}").split()
    if not ids:
        raise ValueError("source project has no containers")
    containers = json.loads(docker("inspect", *(v.decode() for v in ids)))
    for name in ("web", "postgres", "minio"):
        matches = [c for c in containers if service(c) == name]
        if len(matches) != 1 or not matches[0]["State"]["Running"]:
            raise ValueError(f"one running {name} container is required")
    return containers


def pick(containers, name):
    return next(c for c in containers if service(c) == name)


def volumes(containers):
    result = {}
    for c in containers:
        for mount in c["Mounts"]:
            if mount["Type"] == "volume":
                name = mount["Name"]
                item = json.loads(docker("volume", "inspect", name))[0]
                if item["Driver"] != "local" or item.get("Options"):
                    raise ValueError("only local Docker volumes without driver options are supported")
                result[name] = {"service": service(c), "destination": mount["Destination"]}
            elif mount["Type"] != "bind":
                raise ValueError("unsupported persistent mount type")
    return result


def copy_file(source, target):
    if source.is_symlink():
        # Materialize links inside the selected root rather than leaving
        # absolute host paths in a supposedly portable package.
        raise ValueError(f"symlink needs explicit review before packaging: {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_tree(source, target):
    if source.is_file():
        copy_file(source, target)
        return
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"input is not a regular file/directory: {source}")
    target.mkdir(parents=True, exist_ok=True)
    for path in sorted(source.iterdir()):
        copy_tree(path, target / path.name)


def freeze_host(bundle, root, containers):
    # git's index + untracked listing preserves dirty work without committing it.
    names = run(["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"]).split(b"\0")
    for raw in sorted(set(names)):
        if not raw:
            continue
        name = Path(os.fsdecode(raw))
        if name.parts[0] == "backups" or any(name == Path(p) or Path(p) in name.parents for p in INPUTS):
            continue
        source = root / name
        if source.exists():
            copy_file(source, bundle / "source" / name)
    for name in INPUTS:
        if (root / name).exists():
            copy_tree(root / name, bundle / "inputs" / "host" / name)
    for source in [root / ".env", *sorted((root / "env").glob("*.env"))]:
        if source.is_file():
            copy_file(source, bundle / "config" / "host" / source.relative_to(root))
    bind_map = {}
    for c in containers:
        for mount in c["Mounts"]:
            if mount["Type"] != "bind":
                continue
            source = mount["Source"]
            if source not in bind_map:
                relative = f"inputs/binds/{len(bind_map):03d}/{Path(source).name}"
                copy_tree(Path(source), bundle / relative)
                bind_map[source] = relative
    compose_map = {}
    for c in containers:
        for source in c["Config"]["Labels"].get("com.docker.compose.project.config_files", "").split(","):
            if source and source not in compose_map:
                relative = f"config/compose/{len(compose_map):03d}-{Path(source).name}"
                if Path(source).is_file():
                    copy_file(Path(source), bundle / relative)
                    compose_map[source] = relative
                else:
                    # Old deployment overlays can have been removed since
                    # container creation. Exact inspect/image data is saved.
                    compose_map[source] = None
    write_json(bundle / "config" / "bind-map.json", bind_map)
    write_json(bundle / "config" / "compose-map.json", compose_map)
    (bundle / "manifest" / "git-status.txt").write_bytes(run(["git", "-C", str(root), "status", "--short"]))
    (bundle / "manifest" / "working-tree.patch").write_bytes(run(["git", "-C", str(root), "diff", "--binary", "HEAD"]))
    run(["git", "-C", str(root), "bundle", "create", str(bundle / "source" / "repository.bundle"), "--all"])
    for name in ("transfer.py", "transfer-preview.py", "transfer-check.py"):
        copy_file(Path(__file__).parent / name, bundle / name)


def prepare(args):
    bundle = args.bundle.resolve()
    root = args.root.resolve()
    if not bundle.is_relative_to(root / "backups" / "transfer"):
        raise ValueError("prepare destination must be under repository backups/transfer (Git-excluded)")
    containers = inventory(args.project)
    volume_map = volumes(containers)
    image_ids = sorted({c["Image"] for c in containers})
    images = json.loads(docker("image", "inspect", *image_ids))
    if shutil.disk_usage(root).free < sum(i["Size"] for i in images) * 3 + 5 * 1024**3:
        raise ValueError("insufficient free disk space for image preparation")
    bundle.mkdir(parents=True, exist_ok=False, mode=0o700)
    for name in ("source", "database", "volumes", "inputs", "config", "images", "manifest"):
        (bundle / name).mkdir()
    info = {"schema_version": SCHEMA, "state": "preparing", "project": args.project,
            "root": str(root), "prepared_at": datetime.now(timezone.utc).isoformat(),
            "git_commit": run(["git", "-C", str(root), "rev-parse", "HEAD"]).decode().strip(),
            "volumes": volume_map, "images": [{"id": i["Id"], "architecture": i["Architecture"],
                                               "os": i["Os"], "size": i["Size"]} for i in images]}
    write_json(bundle / "config" / "containers.json", containers)
    write_json(bundle / "manifest" / "snapshot.json", info)
    print("Saving exact runtime images (services remain running)...", flush=True)
    docker("image", "save", "--output", bundle / "images" / "runtime.tar", *image_ids)
    # Host data is frozen during capture, not while writers are still active.
    copy_file(Path(__file__).parent / "transfer.py", bundle / "transfer.py")
    copy_file(Path(__file__).parent / "transfer-preview.py", bundle / "transfer-preview.py")
    copy_file(Path(__file__).parent / "transfer-check.py", bundle / "transfer-check.py")
    (bundle / "RESTORE.md").write_text(RESTORE_GUIDE)
    info["state"] = "prepared"
    write_json(bundle / "manifest" / "snapshot.json", info)
    print(f"Prepared: {bundle}\nNot a completed backup: capture is still required.")


@contextmanager
def cron_locks(paths):
    handles = []
    try:
        for path in sorted(set(paths)):
            if not path.is_file():
                raise ValueError("daily cron lock must already exist")
            handle = path.open("r+")
            handles.append(handle)
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        for handle in reversed(handles):
            handle.close()


def check_cron_locks(paths):
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode not in (0, 1):
        raise RuntimeError("cannot inspect cron")
    supplied = {p.resolve() for p in paths}
    for line in result.stdout.splitlines():
        if line.lstrip().startswith("#") or "run-daily-" not in line:
            continue
        tokens = shlex.split(line)
        if "flock" not in tokens:
            raise ValueError("daily cron entry has no flock; quiesce it explicitly before capture")
        i = tokens.index("flock") + 1
        while i < len(tokens) and tokens[i].startswith("-"):
            if tokens[i] in ("-w", "--wait", "--timeout"):
                i += 2
            elif tokens[i] in ("-n", "--nonblock", "-x", "--exclusive"):
                i += 1
            else:
                raise ValueError("unsupported cron flock option; review before capture")
        if i == len(tokens) or Path(os.path.expanduser(tokens[i])).resolve() not in supplied:
            raise ValueError("all daily cron locks must be supplied with --lock-file")


def object_check(containers, *, network=None, database_url=None, bundle):
    web = pick(containers, "web")
    env = dict(v.split("=", 1) for v in web["Config"]["Env"])
    model = pick(containers, "analysis-worker")
    model_env = dict(v.split("=", 1) for v in model["Config"]["Env"])
    minio_env = dict(v.split("=", 1) for v in pick(containers, "minio")["Config"]["Env"])
    payload = {"database_url": database_url or env["BIDOPS_DATABASE_URL"],
               "minio_user": minio_env["MINIO_ROOT_USER"], "minio_password": minio_env["MINIO_ROOT_PASSWORD"],
               "model_key": model_env.get("BIDOPS_MODEL_RESPONSE_ENCRYPTION_KEY", "")}
    script = bundle / "transfer-check.py"
    if network:
        output = docker("run", "--rm", "-i", "--network", network, "--entrypoint", "python",
                        "--mount", f"type=bind,src={script},dst=/check.py,readonly", web["Image"],
                        "/check.py", data=json.dumps(payload).encode())
    else:
        # Existing web shares both database and object-store networks. stdin
        # carries the checker and configuration, without copying into it.
        source = script.read_text()
        program = "import io,sys\nsys.stdin=io.StringIO(" + repr(json.dumps(payload)) + ")\n" + source
        output = docker("exec", "-i", web["Id"], "python", "-", data=program.encode())
    return json.loads(output)


def psql(container, sql):
    return docker("exec", "-i", container, "psql", "-X", "-U", "owner", "-d", "bidops",
                  "-v", "ON_ERROR_STOP=1", "-At", data=sql.encode()).decode()


def db_summary(container):
    names = psql(container, "SELECT tablename FROM pg_tables WHERE schemaname='bidops' ORDER BY tablename;").splitlines()
    if any(not re.fullmatch(r"[a-z_][a-z_0-9]*", n) for n in names):
        raise ValueError("unexpected database identifier")
    counts = {}
    for name in names:
        counts[name] = int(psql(container, f'SELECT count(*) FROM bidops."{name}";').strip())
    revision = psql(container, "SELECT version_num FROM bidops.alembic_version ORDER BY version_num;").splitlines()
    return {"revision": revision, "rows": counts}


def assert_no_active_jobs(container):
    columns = psql(container, """SELECT table_name || '|' || column_name FROM information_schema.columns
        WHERE table_schema='bidops' AND column_name IN ('status','attempt_status','execution_status');""").splitlines()
    active = []
    for value in columns:
        table, column = value.split("|")
        if not all(re.fullmatch(r"[a-z_][a-z_0-9]*", n) for n in (table, column)):
            raise ValueError("unexpected database identifier")
        count = int(psql(container, f"SELECT count(*) FROM bidops.\"{table}\" WHERE \"{column}\"::text IN ('running','진행 중','실행 중','실행중','처리 중');").strip())
        if count:
            active.append(f"{table}={count}")
    if active:
        raise ValueError("active jobs must finish before capture: " + ", ".join(active))


def archive_volume(image, volume, output):
    with output.open("wb") as stream:
        docker("run", "--rm", "--network", "none", "--user", "0:0", "--entrypoint", "tar",
               "--mount", f"type=volume,src={volume},dst=/snapshot,readonly",
               image, "--numeric-owner", "-C", "/snapshot", "-cpf", "-", ".", output=stream)


def file_manifest(bundle):
    entries = {}
    for path in sorted(bundle.rglob("*")):
        if path.is_symlink():
            raise ValueError("transfer folder must not contain symlinks")
        if path.is_file() and path != bundle / "manifest" / "files.json":
            entries[path.relative_to(bundle).as_posix()] = {"size": path.stat().st_size, "sha256": digest(path)}
    return {"schema_version": SCHEMA, "files": entries}


def capture(args):
    bundle = args.bundle.resolve()
    info = read_json(bundle / "manifest" / "snapshot.json")
    if info["schema_version"] != SCHEMA or info["state"] != "prepared":
        raise ValueError("capture requires an unused prepared folder")
    if not args.confirmed_stop:
        raise ValueError("capture stops production writers: explicitly pass --confirmed-stop after operator approval")
    before = read_json(bundle / "config" / "containers.json")
    now = inventory(info["project"])
    if {(c["Id"], c["Image"], c["State"]["Running"]) for c in now} != {(c["Id"], c["Image"], c["State"]["Running"]) for c in before}:
        raise ValueError("runtime changed after prepare; create a new prepared folder")
    db = pick(now, "postgres")["Id"]
    minio = pick(now, "minio")["Id"]
    stopped = []
    check_cron_locks(args.lock_file)
    with cron_locks(args.lock_file):
        assert_no_active_jobs(db)
        info["state"] = "capturing"
        write_json(bundle / "manifest" / "snapshot.json", info)
        try:
            # Stop precisely the originally running containers. An already
            # stopped analysis worker must not be started by the cleanup path.
            for c in now:
                if c["State"]["Running"] and service(c) not in {"postgres", "minio", "clamav"}:
                    stopped.append(c["Id"])
                    write_json(bundle / "manifest" / "resume-containers.json", stopped)
                    docker("stop", "--time", "60", c["Id"])
            assert_no_active_jobs(db)
            print("Writers stopped; copying database, objects and host inputs...", flush=True)
            write_json(bundle / "manifest" / "database.json", db_summary(db))
            with (bundle / "database" / "bidops.dump").open("wb") as stream:
                docker("exec", db, "pg_dump", "-U", "owner", "-d", "bidops", "-Fc", output=stream)
            with (bundle / "database" / "roles.sql").open("wb") as stream:
                docker("exec", db, "pg_dumpall", "-U", "owner", "--roles-only", output=stream)
            with (bundle / "database" / "bidops.dump").open("rb") as stream:
                result = subprocess.run(["docker", "exec", "-i", db, "pg_restore", "--list"],
                                        stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                if result.returncode:
                    raise RuntimeError("database dump list validation failed")
            write_json(bundle / "manifest" / "objects.json", source_object_check(now, bundle))
            stopped.append(minio)
            write_json(bundle / "manifest" / "resume-containers.json", stopped)
            docker("stop", "--time", "60", minio)
            pg_volumes = {m["Name"] for m in pick(now, "postgres")["Mounts"] if m["Type"] == "volume"}
            for name in info["volumes"]:
                if name not in pg_volumes:
                    archive_volume(pick(now, "postgres")["Image"], name, bundle / "volumes" / f"{name}.tar")
            freeze_host(bundle, Path(info["root"]), now)
            cron = subprocess.run(["crontab", "-l"], capture_output=True)
            if cron.returncode not in (0, 1):
                raise RuntimeError("could not preserve crontab")
            (bundle / "config" / "crontab.txt").write_bytes(cron.stdout)
        finally:
            errors = []
            # Object store first; then conversion/model services; web last.
            for cid in reversed(stopped):
                try:
                    docker("start", cid)
                    if cid in {minio, pick(now, "web")["Id"]}:
                        wait_healthy(cid)
                except Exception:
                    errors.append(cid[:12])
            if errors:
                raise RuntimeError("source service resume failed: " + ", ".join(errors))
    info["state"] = "captured"
    info["captured_at"] = datetime.now(timezone.utc).isoformat()
    info["validation"] = "file hashes only; isolated restore verification required"
    write_json(bundle / "manifest" / "snapshot.json", info)
    write_json(bundle / "manifest" / "files.json", file_manifest(bundle))
    print(f"Captured: {bundle}\nSource services resumed. Run verify and isolated restore before relying on this folder.")


def verify(bundle):
    manifest = read_json(bundle / "manifest" / "files.json")
    info = read_json(bundle / "manifest" / "snapshot.json")
    if manifest["schema_version"] != SCHEMA or info["state"] != "captured":
        raise ValueError("not a completed capture")
    if file_manifest(bundle) != manifest:
        raise ValueError("transfer file set, size or SHA-256 differs from manifest")
    print("All transfer files match the manifest.", flush=True)


def wait_healthy(cid):
    for _ in range(90):
        state = json.loads(docker("inspect", cid))[0]["State"]
        if state.get("Health", {}).get("Status") == "healthy":
            return
        if not state["Running"]:
            break
        time.sleep(1)
    raise RuntimeError("restored/source container did not become healthy")


def escape_compose(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [escape_compose(v) for v in value]
    if isinstance(value, dict):
        return {k: escape_compose(v) for k, v in value.items()}
    return value


def compose_config(bundle, containers, project, port, *, volume_names):
    binds = read_json(bundle / "config" / "bind-map.json")
    volume_map = {name: f"volume-{n}" for n, name in enumerate(volume_names)}
    result = {"services": {}, "volumes": {v: {} for v in volume_map.values()},
              "networks": {"private": {"internal": True}, "edge": {}}}
    for name in ("postgres", "minio", "web"):
        c = pick(containers, name)
        cfg = c["Config"]
        env = dict(v.split("=", 1) for v in cfg["Env"])
        item = {"image": c["Image"], "pull_policy": "never", "environment": env,
                "networks": ["private"], "volumes": [], "restart": "no"}
        for src, dst in (("Cmd", "command"), ("Entrypoint", "entrypoint"), ("User", "user"), ("WorkingDir", "working_dir")):
            if cfg.get(src):
                item[dst] = cfg[src]
        hc = cfg.get("Healthcheck")
        if hc:
            item["healthcheck"] = {"test": hc["Test"], "interval": "3s", "timeout": "5s", "retries": 30}
        for mount in c["Mounts"]:
            spec = {"type": mount["Type"], "target": mount["Destination"]}
            if mount["Type"] == "volume":
                spec["source"] = volume_map[mount["Name"]]
            else:
                spec.update(source=str(bundle / binds[mount["Source"]]), read_only=True,
                            bind={"create_host_path": False})
            item["volumes"].append(spec)
        if name == "web":
            env.update({flag: "false" for flag in OFF_FLAGS})
            env["PGOPTIONS"] = "-c default_transaction_read_only=on"
            item["entrypoint"] = ["python", "-m", "uvicorn"]
            item["command"] = ["transfer-preview:app", "--app-dir", "/transfer", "--host", "0.0.0.0", "--port", "8787"]
            item["networks"].append("edge")
            item["ports"] = [f"127.0.0.1:{port}:8787"]
            item["volumes"].append({"type": "bind", "source": str(bundle / "transfer-preview.py"),
                                    "target": "/transfer/transfer-preview.py", "read_only": True,
                                    "bind": {"create_host_path": False}})
        result["services"][name] = item
    return escape_compose(result), volume_map


def restore(args):
    bundle = args.bundle.resolve()
    verify(bundle)
    info = read_json(bundle / "manifest" / "snapshot.json")
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,50}", args.project) or args.project == info["project"]:
        raise ValueError("choose a new project name, different from the source")
    if not 1024 <= args.port <= 65535:
        raise ValueError("port must be between 1024 and 65535")
    target = args.target.resolve()
    if target.exists() or target.is_relative_to(bundle):
        raise ValueError("restore target directory must be new and outside the immutable bundle")
    for kind in ("container", "volume", "network"):
        flags = ["-a"] if kind == "container" else []
        if docker(kind, "ls", *flags, "-q", "--filter", f"label=com.docker.compose.project={args.project}").strip():
            raise ValueError("restore project already has Docker resources")
    containers = read_json(bundle / "config" / "containers.json")
    # Refuse silent cross-architecture emulation; keep image bytes unchanged.
    arch = docker("info", "--format", "{{.Architecture}}").decode().strip()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(arch, arch)
    if any(i["architecture"] != arch for i in info["images"]):
        raise ValueError("restore host architecture must match the saved runtime images")
    # Use saved volume metadata, not docker volume inspect on the new host.
    config, vmap = compose_config_offline(bundle, containers, args.project, args.port, info)
    for v in vmap.values():
        if subprocess.run(["docker", "volume", "inspect", f"{args.project}_{v}"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
            raise ValueError("target volume name already exists")
    target.mkdir(parents=True, mode=0o700)
    write_json(target / "compose.json", config)
    command = ["docker", "compose", "-p", args.project, "-f", str(target / "compose.json")]
    run(command + ["config", "--quiet"])
    # Validate every archive before creating any Docker resource.
    for name in vmap:
        archive = bundle / "volumes" / f"{name}.tar"
        if archive.exists():
            validate_archive(archive, mountpoint=info["volumes"][name]["destination"])
    print("Loading images and creating an isolated restore target...", flush=True)
    docker("image", "load", "--input", bundle / "images" / "runtime.tar")
    run(command + ["create", "--no-build", "postgres", "minio", "web"])
    helper = pick(containers, "postgres")["Image"]
    for name, volume in vmap.items():
        archive = bundle / "volumes" / f"{name}.tar"
        if not archive.exists():
            continue  # PostgreSQL is restored from the logical dump below.
        with archive.open("rb") as stream:
            result = subprocess.run(["docker", "run", "--rm", "-i", "--network", "none", "--user", "0:0",
                                     "--entrypoint", "tar", "--mount", f"type=volume,src={args.project}_{volume},dst=/snapshot",
                                     helper, "--numeric-owner", "-C", "/snapshot", "-xpf", "-"],
                                    stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            if result.returncode:
                raise RuntimeError("volume extraction failed")
    run(command + ["start", "postgres", "minio"])
    db = run(command + ["ps", "-q", "postgres"]).decode().strip()
    minio = run(command + ["ps", "-q", "minio"]).decode().strip()
    wait_healthy(db)
    wait_healthy(minio)
    if psql(db, "SELECT count(*) FROM pg_tables WHERE schemaname='bidops';").strip() != "0":
        raise ValueError("restore database is not empty")
    roles = (bundle / "database" / "roles.sql").read_text()
    # initdb already created owner. Keep ALTER ROLE (including password and
    # attributes), all other roles, and memberships from pg_dumpall intact.
    roles = re.sub(r"^CREATE ROLE owner;\n", "", roles, flags=re.MULTILINE)
    psql(db, roles)
    with (bundle / "database" / "bidops.dump").open("rb") as stream:
        result = subprocess.run(["docker", "exec", "-i", db, "pg_restore", "--exit-on-error",
                                 "-U", "owner", "-d", "bidops"], stdin=stream,
                                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if result.returncode:
            raise RuntimeError("database restore failed; target remains isolated for diagnosis")
    actual = db_summary(db)
    if actual != read_json(bundle / "manifest" / "database.json"):
        raise ValueError("restored database revision/row counts differ")
    run(command + ["start", "web"])
    web = run(command + ["ps", "-q", "web"]).decode().strip()
    wait_healthy(web)
    actual_objects = object_check(containers, network=f"{args.project}_private", bundle=bundle)
    if actual_objects != read_json(bundle / "manifest" / "objects.json"):
        raise ValueError("restored object versions, hashes or reference checks differ from the source")
    write_json(target / "validation.json", {"schema_version": SCHEMA, "database": actual,
               "status": "database-objects-and-health-verified", "object_versions": len(actual_objects["versions"]),
               "source_object_issues": actual_objects["issues"], "remaining": "representative API verification"})
    print(f"Restored browse mode: http://127.0.0.1:{args.port}\nCompose: {target / 'compose.json'}")


def compose_config_offline(bundle, containers, project, port, info):
    return compose_config(bundle, containers, project, port, volume_names=info["volumes"])


def source_object_check(containers, bundle):
    # A temporary helper joins only the existing internal DB/storage networks.
    # It performs SELECT and object GET/list; it has no production entrypoint.
    web = pick(containers, "web")
    networks = set(pick(containers, "postgres")["NetworkSettings"]["Networks"])
    networks |= set(pick(containers, "minio")["NetworkSettings"]["Networks"])
    name = "bidops-transfer-check-" + os.urandom(6).hex()
    first, *rest = sorted(networks)
    helper = docker("create", "--name", name, "--network", first, "--entrypoint", "sleep", web["Image"], "300").decode().strip()
    try:
        for network in rest:
            docker("network", "connect", network, helper)
        docker("start", helper)
        modified = [{**c, "Id": helper} if service(c) == "web" else c for c in containers]
        return object_check(modified, bundle=bundle)
    finally:
        docker("rm", "-f", helper)


def validate_archive(path, *, mountpoint=None):
    links = set()
    names = []
    with tarfile.open(path) as archive:
        for item in archive:
            name = PurePosixPath(item.name)
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("volume archive contains an unsafe path or unsupported entry")
            names.append(name)
            if item.issym():
                target = PurePosixPath(item.linkname)
                if target.is_absolute():
                    normalized = PurePosixPath(posixpath.normpath(str(target)))
                    if not mountpoint or not normalized.is_relative_to(PurePosixPath(mountpoint)):
                        raise ValueError("volume symlink escapes its runtime mount")
                else:
                    normalized = PurePosixPath(posixpath.normpath(str(name.parent / target)))
                    if ".." in normalized.parts:
                        raise ValueError("volume symlink escapes its archive")
                links.add(name)
            elif not (item.isfile() or item.isdir()):
                raise ValueError("volume archive contains an unsupported entry")
    if any(parent in links for name in names for parent in name.parents):
        raise ValueError("archive member traverses a symlink")


RESTORE_GUIDE = """# BidOps 이전본

이 폴더 전체를 복사한다. 평문 회사자료·환경 설정·복호화 키·인증 파일이 포함되므로 Git에 넣지 않는다.
`manifest/snapshot.json`의 state가 captured이고 `manifest/files.json`이 있어야 완료된 백업이다.

## 새 서버에서 열기

Linux, Python 3.12+, Docker Engine 및 Compose v2, 원본과 같은 CPU 아키텍처가 필요하다.
이미지가 포함돼 있으므로 앱 빌드·모델 서버·나라장터 API는 필요 없다.
복원 공간은 이전 폴더 외에도 이미지와 DB·볼륨 복제 공간이 필요하다.

```bash
python3 /path/to/transfer/transfer.py verify --bundle /path/to/transfer
python3 /path/to/transfer/transfer.py restore --bundle /path/to/transfer \\
  --project bidops-restored --target /path/to/new-restore --port 18789
```

http://127.0.0.1:18789 에서 저장된 데이터를 열람한다. 변경 요청은 405로 막고,
웹 내장 판정 워커·일정·별도 워커를 시작하지 않는다. DB 연결도 read-only transaction이다.
기존 policy 활성화 값과 품질 상태는 보존되지만 자동 실행은 꺼져 있다.
복원 실패 시 대상만 남긴다. 기존 대상 위 재실행은 거부하므로 원인을 확인한 뒤 새 프로젝트를 쓴다.

```bash
docker compose -p bidops-restored -f /path/to/new-restore/compose.json stop
docker compose -p bidops-restored -f /path/to/new-restore/compose.json start
```

## 포함 범위와 운영 전환

- source/: 미커밋 작업을 포함한 소스 사본과 repository.bundle. 실행은 저장된 이미지가 기준이다.
- inputs/host/: 호스트 회차·실험 입력·보고서. Docker 볼륨의 동명 경로와 합치지 않는다.
- inputs/binds/, config/: 실제 마운트 입력과 운영 설정. 경로 대응표가 함께 있다.
- database/: 전체 DB dump와 역할. volumes/: MinIO 전체 메타데이터·객체 버전과 앱 데이터.
- images/: 현재 서비스별 이미지. 이미 중지된 분석 워커 이미지도 보존한다.
- manifest/: 기준 커밋·변경 목록·DB revision/행 수·파일 해시.

Git 추적 파일의 권한과 볼륨 소유권은 보존한다. tar 파일을 클라우드 앱에서 풀지 않는다.
수집 회차의 같은 볼륨 내부 심볼릭 링크는 원래 컨테이너 경로로 보존한다.
외부 경로 링크와 링크를 통해 다른 파일을 쓰는 archive는 복원 전에 거부한다.
MinIO 전체 볼륨을 동일 이미지로 복원하므로 객체 version ID를 다시 발급하지 않는다.
DB migration이나 minio-init을 이 복원 절차에 추가하지 않는다.

이것은 저장된 결과 열람용 복원이다. 새 서버에서 실제 수집·분석을 켜는 작업은 별도 운영 전환이다.
config/crontab.txt는 보관만 하며 자동 설치하지 않는다. 복원용 서비스에는 운영 포트·외부
모델 네트워크·codex 인증 마운트를 연결하지 않는다. 새 자격증명은 운영 전환 때 재설정하며,
기존 암호화 응답을 읽을 원래 복호화 키는 유지해야 한다.
시간이 지난 뒤 시연할 때는 목록의 전체 이력과 날짜 필터를 사용한다. 원래 게시일·마감일을
현재 날짜로 바꾸지 않는다.
"""


def main():
    os.umask(0o077)
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt("interrupted; source resume cleanup will run")
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("prepare", "capture", "verify", "restore"):
        sub = commands.add_parser(name)
        sub.add_argument("--bundle", required=True, type=Path)
        if name == "prepare":
            sub.add_argument("--root", type=Path, default=ROOT)
            sub.add_argument("--project", required=True)
        if name == "capture":
            sub.add_argument("--lock-file", type=Path, action="append", required=True)
            sub.add_argument("--confirmed-stop", action="store_true")
        if name == "restore":
            sub.add_argument("--project", required=True)
            sub.add_argument("--target", type=Path, required=True)
            sub.add_argument("--port", type=int, default=18789)
    args = parser.parse_args()
    try:
        if args.command == "verify":
            verify(args.bundle.resolve())
        else:
            globals()[args.command](args)
    except (Exception, KeyboardInterrupt) as error:
        print(f"Transfer failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
