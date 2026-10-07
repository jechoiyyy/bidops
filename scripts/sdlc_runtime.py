"""SDLC v2 paths, stable tasks, evidence and upgrade commands (stdlib only)."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

VERSION = "0.6.0"
SCHEMA = 2
API = {}


def bind(api):
    API.update(api)


def read(path, default=None):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else copy.deepcopy(default)


def write(path, data):
    API["atomic_json"](path, data)


def stamp():
    return API["now"]()


def fail(message):
    raise ValueError(message)


def safe(root, relative):
    candidate = (root / relative).resolve()
    if not candidate.is_relative_to(root.resolve()) or candidate == root.resolve():
        fail(f"프로젝트 밖 또는 루트 경로 금지: {relative}")
    return candidate


def group_id(value):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        fail(f"그룹 ID 형식 오류: {value}")
    return value


def groups(project):
    data = read(project.work_dir / "groups.json", {"schema_version": SCHEMA, "groups": []})
    ids = data["groups"]
    if len(ids) != len(set(ids)):
        fail("중복 그룹 ID")
    for value in ids:
        group_id(value)
    return data


def status_paths(project, group=None):
    paths = sorted([*project.work_dir.glob("*/status.json"), *project.work_dir.glob("groups/*/features/*/status.json")])
    result, seen = [], set()
    for path in paths:
        if path.parent.name.startswith("_"):
            continue
        safe(project.root, path.relative_to(project.root))
        data = read(path)
        slug = data.get("feature")
        if slug != path.parent.name or not project.id_re.fullmatch(slug or ""):
            fail(f"기능 ID/경로 불일치: {path}")
        if slug in seen:
            fail(f"중복 기능 ID: {slug}")
        seen.add(slug)
        nested = path.parent.parent.name == "features"
        if nested and path.parent.parent.parent.name not in groups(project)["groups"]:
            fail(f"등록되지 않은 그룹: {path}")
        if not group or (nested and path.parent.parent.parent.name == group):
            result.append(path)
    return result


def resolve(project, slug):
    if not project.id_re.fullmatch(slug) or "/" in slug or "\\" in slug:
        fail(f"기능 ID 형식 오류: {slug}")
    found = [p.parent for p in status_paths(project) if p.parent.name == slug]
    if not found:
        raise FileNotFoundError(f"기능 없음: {slug}; init <ID> --group <그룹> 사용")
    return found[0]


def feature_group(project, slug):
    path = resolve(project, slug)
    return path.parent.parent.name if path.parent.name == "features" else None


def cmd_group(project, args):
    data = groups(project)
    if args.action == "add":
        gid = group_id(args.slug)
        if gid not in data["groups"]:
            data["groups"].append(gid)
            write(project.work_dir / "groups.json", data)
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_resolve(project, args):
    print(resolve(project, args.slug))


def cmd_resolve_path(project, args):
    path = safe(project.root, args.slug)
    folder = project.work_dir / "_migrations"
    journals = [read(p) for p in sorted((folder / "history").glob("*.json"))]
    current = read(folder / "layout-v2.json")
    if current:
        journals.append(current)
    moves = [move for journal in journals if journal.get("state") == "complete" for move in journal["moves"]]
    for move in moves:
        old = project.root / move["old"]
        if path == old or path.is_relative_to(old):
            path = project.root / move["new"] / path.relative_to(old)
    if not path.exists():
        fail(f"과거 경로에 대응하는 파일 없음: {args.slug}")
    print(path)


def write_migration(path, journal):
    previous = read(path)
    if previous and previous.get("state") == "complete":
        history_dir = path.parent / "history"
        sequence = len(list(history_dir.glob("*.json")))
        history = history_dir / (f"{sequence:06}-" + digest(json.dumps(previous, sort_keys=True))[:8] + ".json")
        write(history, previous)
    write(path, journal)


def cmd_init(project, args):
    if not project.id_re.fullmatch(args.slug):
        fail("잘못된 기능 ID")
    if any(p.parent.name == args.slug for p in status_paths(project)):
        fail(f"이미 존재: {args.slug}")
    gid = args.group or project.config.get("default_group")
    if not gid or gid not in groups(project)["groups"]:
        fail("등록된 --group 필요: group <그룹> add")
    directory = safe(project.root, project.work_dir.relative_to(project.root) / "groups" / gid / "features" / args.slug)
    if directory.exists():
        fail(f"기존 디렉터리 보존: {directory}")
    directory.mkdir(parents=True)
    data = {"schema_version": SCHEMA, "feature": args.slug, "phase": "drafting", "steps": [],
            "proof": {key: {"result": "pending"} for key in project.proof_keys}, "notes": [], "updated_at": None}
    API["add_note"](data, "생성 (drafting)")
    API["save"](directory / "status.json", data)
    print(directory)


def digest(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def parse_steps(project, path):
    text = path.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(project.steps_heading)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    if not match:
        fail(f"작업 순서 절 없음: {path}")
    blocks = list(re.finditer(r"^\d+\.\s+(.+)$([\s\S]*?)(?=^\d+\.\s|\Z)", match[1], re.M))
    result = []
    for block in blocks:
        title, body = block[1].strip(), block[2].strip()
        model = project.default_model
        tag = API["TAG_RE"].search(title)
        if tag:
            model, title = tag[1], title[:tag.start()].strip()
        if model not in project.agents:
            fail(f"모르는 실행 프로필: {model}")
        task = re.match(r"(?:\[)?(STEP-\d{3,})(?:\])?\s+(.+)", title)
        tid = task[1] if task else None
        title = task[2] if task else title
        result.append({"id": tid, "title": title, "model": model,
                       "fingerprint": digest(title + "\n" + body)})
    if not result:
        fail("작업 순서가 비어 있음")
    explicit = [s["id"] for s in result if s["id"]]
    if len(explicit) != len(set(explicit)):
        fail("중복 STEP ID")
    return result


def sync_result(project, path, data):
    parsed = parse_steps(project, path)
    retired = {s["id"] for s in data.get("retired_steps", [])}
    if any(s["id"] in retired for s in parsed if s["id"]):
        fail("폐기된 STEP ID 재사용 금지")
    previous = data.get("steps", [])
    old_ids = {str(s["id"]): s for s in previous}
    used = set()
    number = max([int(str(s["id"])[5:]) for s in previous if str(s["id"]).startswith("STEP-")] + [0])
    reserved = {s["id"] for s in parsed if s["id"]} | set(old_ids) | retired
    output = []
    for step in parsed:
        old = old_ids.get(step["id"]) if step["id"] else None
        if old is None and (not step["id"] or any(isinstance(s["id"], int) for s in previous)):
            candidates = [s for s in previous if s["title"] == step["title"] and str(s["id"]) not in used]
            if len(candidates) > 1:
                fail("이전 단계 제목이 중복됨. ID를 명시하고 수동으로 매핑해야 함")
            old = candidates[0] if candidates else None
        if old:
            used.add(str(old["id"]))
        if step["id"] is None:
            if old and str(old["id"]).startswith("STEP-"):
                step["id"] = old["id"]
            else:
                number += 1
                while f"STEP-{number:03}" in reserved:
                    number += 1
                step["id"] = f"STEP-{number:03}"
                reserved.add(step["id"])
        item = {**(old or {}), **step}
        item.setdefault("status", "pending")
        item.setdefault("updated_at", None)
        if old and isinstance(old["id"], int):
            item["legacy_id"] = old["id"]
            if old["status"] == "done":
                item["status"] = "stale"  # old parser did not record the step body
        if old and old.get("fingerprint") and old["fingerprint"] != step["fingerprint"]:
            item.setdefault("history", []).append(copy.deepcopy(old))
            item["status"] = "stale"
        output.append(item)
    lost = [s for s in previous if str(s["id"]) not in used and s["status"] != "pending"]
    if lost:
        fail("진행/완료 단계 삭제 감지: 명시적으로 이력을 보존하고 replan 필요")
    return output


def cmd_sync(project, args):
    path, data = project.load(args.slug)
    steps = sync_result(project, path.parent / "plan.md", data)
    changed = steps != data["steps"]
    if args.command == "check-plan":
        if changed:
            fail("plan/status 불일치: sync-plan 필요")
        print("plan 일치")
        return
    if changed:
        data["steps"] = steps
        data["schema_version"] = SCHEMA
        invalidate(data, "작업 계약 변경")
        API["add_note"](data, "plan 작업 ID 동기화")
        API["save"](path, data)
    print("\n".join(API["format_step"](s) for s in steps))


def proof_def(project, key):
    value = project.config["proof"][key]
    return {"required": True, "method": "command" if project.config.get("commands", {}).get(key) else "manual",
            "applies_when": "항상", **({"description": value} if isinstance(value, str) else value)}


def conditional_proof(definition):
    condition = str(definition.get("applies_when", "항상")).strip().lower()
    return bool(condition) and condition not in ("항상", "always", "true", "all")


def result(proof):
    return proof if isinstance(proof, str) else proof.get("result", "pending")


def invalidate(data, reason):
    for key, value in data["proof"].items():
        if result(value) in ("pass", "not_applicable"):
            data["proof"][key] = {**({} if isinstance(value, str) else value), "result": "stale", "reason": reason}
    if data["phase"] == "done":
        data["phase"] = "validating"
    data.pop("integration", None)


def git(root, *args, check=True):
    proc = subprocess.run(["git", "-C", str(root), *args], text=True, capture_output=True)
    if check and proc.returncode:
        fail(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip() if proc.returncode == 0 else None


def snapshot(project, slug):
    """Hash tested inputs, independent of commits and mutable evidence records."""
    directory = resolve(project, slug)
    spec = {}
    for name in ("intent.md", "spec.md", "plan.md"):
        text = (directory / name).read_text(encoding="utf-8")
        if name == "plan.md":
            text = re.split(r"^## 결과\s*$", text, maxsplit=1, flags=re.M)[0]
        spec[name] = text
    policy = copy.deepcopy(project.config)
    policy.pop("tool_version", None)
    spec["policy"] = policy
    constitution = project.config.get("constitution_dir", "specs")
    for name in ("mission.md", "tech-stack.md", "roadmap.md"):
        path = safe(project.root, Path(constitution) / name)
        spec[str(Path(constitution) / name)] = path.read_text() if path.exists() else None
    listing = git(project.root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", check=False)
    if listing is None:
        fail("검증 증거 기록에는 Git 저장소 필요 (init 문서 작성에는 불필요)")
    code = {}
    for relative in sorted(set(listing.split("\0")) - {""}):
        path = project.root / relative
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if path.is_relative_to(project.work_dir) or relative == "CHANGELOG.md":
            continue
        if path.is_symlink():
            code[relative] = "symlink:" + os.readlink(path)
        elif path.is_file():
            code[relative] = digest(path.read_bytes()) + ":" + str(path.stat().st_mode & 0o111)
        elif not path.exists():
            code[relative] = "deleted"
    return {"source_hash": digest(json.dumps(code, sort_keys=True)),
            "spec_hash": digest(json.dumps(spec, ensure_ascii=False, sort_keys=True))}


def proof_errors(project, slug, data, contract_only=False):
    current = snapshot(project, slug)
    errors = []
    for key in project.proof_keys:
        definition = proof_def(project, key)
        if not definition["required"] or (contract_only and not definition.get("dependency_gate", True)):
            continue
        value = data["proof"].get(key, "pending")
        if not isinstance(value, dict) or result(value) not in ("pass", "not_applicable"):
            errors.append(f"{key}: {result(value)}")
        elif any(value.get(k) != v for k, v in current.items()):
            errors.append(f"{key}: stale (입력 변경)")
        elif result(value) == "not_applicable" and (not value.get("note") or not conditional_proof(definition)):
            errors.append(f"{key}: 비적용 불가 또는 근거 없음")
    return errors


def completion_errors(project, slug, data):
    errors = []
    if not data["steps"] or any(s["status"] != "done" for s in data["steps"]):
        errors.append("미완료 작업")
    if sync_result(project, resolve(project, slug) / "plan.md", data) != data["steps"]:
        errors.append("plan 동기화 필요")
    if data["phase"] == "blocked":
        errors.append("blocked 해소 필요")
    errors.extend(proof_errors(project, slug, data))
    return errors


def cmd_phase(project, args):
    path, data = project.load(args.slug)
    target = "done" if args.command == "complete" else args.phase
    if target == "done":
        errors = completion_errors(project, args.slug, data)
        if not data.get("integration") or data["integration"].get("source_hash") != snapshot(project, args.slug)["source_hash"]:
            errors.append("현재 코드의 최종 통합 기록 없음: run finish 필요")
        if errors:
            fail("완료 불가: " + "; ".join(errors))
    if target == "blocked":
        if not args.note:
            fail("blocked 이유 필요")
        if data["phase"] != "blocked":
            data["resume_phase"] = data["phase"]
    allowed = {"drafting": {"review", "blocked"}, "review": {"drafting", "implementing", "blocked"},
               "implementing": {"validating", "blocked"}, "validating": {"implementing", "done", "blocked"},
               "done": {"validating", "blocked"}, "blocked": {data.get("resume_phase", "review")}}
    if target != data["phase"] and target not in allowed.get(data["phase"], set()):
        fail(f"전이 불가: {data['phase']} → {target}")
    if target == "implementing":
        run = active_run(project)
        if not run or args.slug not in run[1]["features"]:
            fail("승인된 활성 run 필요: /sdlc:loop 사용")
        record = run[1]
        if project.root != Path(record["workspace"]):
            expected_branch = f"sdlc/{record['id']}-{args.slug}"
            if git(project.root, "branch", "--show-current") != expected_branch:
                fail("승인된 배치/기능 worktree에서 구현해야 함")
        if data["phase"] == "review":
            _, queue = API["load_queue"](project)
            item = next((item for item in queue["items"] if item["feature"] == args.slug), {})
            for dependency in item.get("depends_on", []):
                _, prior = project.load(dependency)
                if dependency in record["features"]:
                    ready = record.get("ready", {})
                    marked = ready.get(dependency) if isinstance(ready, dict) else None
                    if (not marked or prior["phase"] not in ("validating", "done")
                            or not prior["steps"] or any(step["status"] != "done" for step in prior["steps"])
                            or marked.get("inputs") != snapshot(project, dependency)
                            or proof_errors(project, dependency, prior, contract_only=True)):
                        fail(f"선행 기능 계약 미검증/미통합: {dependency}")
                elif project.phase_of(dependency) != "done" or completion_errors(project, dependency, prior):
                    fail(f"범위 밖 선행 기능 미검증: {dependency}")
    data["phase"] = target
    API["add_note"](data, f"단계 → {target}" + (f": {args.note}" if args.note else ""))
    API["save"](path, data)
    print(target)


def cmd_step(project, args):
    path, data = project.load(args.slug)
    step = next((s for s in data["steps"] if str(s["id"]) == args.id), None)
    if step is None:
        fail(f"단계 ID 없음: {args.id}; 표시 순번 대신 STEP ID 사용")
    if args.status == "blocked" and not args.note:
        fail("blocked 이유 필요")
    step["status"], step["updated_at"] = args.status, stamp()
    if args.note:
        step["note"] = args.note
    invalidate(data, "작업 상태 변경")
    API["add_note"](data, f"단계 {args.id} {args.status}: {args.note or ''}")
    API["save"](path, data)


def cmd_proof(project, args):
    path, data = project.load(args.slug)
    if args.key not in project.proof_keys:
        fail("설정에 없는 proof")
    if args.status in ("not_applicable", "skipped", "fail") and not args.note:
        fail("결과 이유 필요")
    definition = proof_def(project, args.key)
    if args.status == "not_applicable" and not conditional_proof(definition):
        fail("항상 적용되는 검증은 not_applicable로 면제할 수 없음")
    if args.status in ("pass", "not_applicable") and not args.evidence:
        fail("--evidence 경로 또는 확인 근거 필요")
    if args.status == "pass" and definition["method"] == "command" and args.exit_code != 0:
        fail("명령 proof pass에는 --exit-code 0 필요")
    evidence = {"result": args.status, "method": definition["method"], "note": args.note,
                "evidence": args.evidence, "exit_code": args.exit_code, "actor": args.actor,
                "command": project.config.get("commands", {}).get(args.key), "at": stamp(),
                "head": git(project.root, "rev-parse", "HEAD", check=False), **snapshot(project, args.slug)}
    old = data["proof"].get(args.key)
    data.setdefault("proof_history", []).append({"key": args.key, "previous": old})
    data["proof"][args.key] = evidence
    if args.status not in ("pass", "not_applicable") and data["phase"] == "done":
        data["phase"] = "validating"
    API["save"](path, data)


def cmd_check(project, args):
    path, data = project.load(args.slug)
    errors = completion_errors(project, args.slug, data)
    if errors:
        fail("; ".join(errors))
    print("필수 검증 충족 (최종 통합과 완료는 별도)")


def cmd_reopen(project, args):
    if active_run(project):
        fail("활성 run을 먼저 재개/종료한 뒤 기능 재검증을 연다")
    path, data = project.load(args.slug)
    previous = {key: copy.deepcopy(value) for key, value in data.items() if key != "revisions"}
    data.setdefault("revisions", []).append({"at": stamp(), "reason": args.note, "status": previous})
    data["steps"] = sync_result(project, path.parent / "plan.md", data)
    data["schema_version"] = SCHEMA
    invalidate(data, args.note)
    data["phase"] = "review"
    data.pop("resume_phase", None)
    API["add_note"](data, "재검증 실행 준비: " + args.note)
    API["save"](path, data)
    print("review: 기존 이력을 보존하고 검증 run을 시작할 수 있음")


def cmd_retire(project, args):
    path, data = project.load(args.slug)
    step = next((s for s in data["steps"] if s["id"] == args.id), None)
    if not step:
        fail("작업 ID 없음")
    data.setdefault("retired_steps", []).append({**step, "retired_at": stamp(), "reason": args.note})
    data["steps"].remove(step)
    invalidate(data, args.note)
    API["add_note"](data, f"작업 폐기 {args.id}: {args.note}")
    API["save"](path, data)


def cmd_invalidate(project, args):
    path, data = project.load(args.slug)
    invalidate(data, args.note)
    API["add_note"](data, "재검증: " + args.note)
    API["save"](path, data)


def cmd_doctor(project, args):
    if project.config.get("schema_version", 1) > SCHEMA:
        fail("도구보다 새로운 schema: 플러그인/프로젝트 도구 upgrade 필요")
    paths = status_paths(project)
    _, queue = API["load_queue"](project)
    API["validate_queue"](queue["items"])
    for item in queue["items"]:
        resolve(project, item["feature"])
    for item in project.config.get("big_picture_docs", []):
        if not safe(project.root, item).is_file():
            fail(f"참조 문서 없음: {item}")
    print(f"doctor: {len(paths)} features, schema={project.config.get('schema_version', 1)}, tool={VERSION}")


def merge_defaults(current, default):
    result = copy.deepcopy(current)
    for key, value in default.items():
        if key not in result:
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result[key], dict):
            result[key] = merge_defaults(result[key], value)
    return result


def cmd_setup(args):
    plugin = Path(__file__).resolve().parent.parent
    if not (plugin / "templates" / "feature.json").is_file():
        fail("setup/upgrade는 설치된 플러그인 원본 scripts/feature_status.py에서 실행")
    root = Path(args.root).resolve()
    work = safe(root, args.work_dir)
    config_path = work / "feature.json"
    old = read(config_path, {})
    if old and args.command == "setup":
        fail("기존 설정 보존: setup --force 대신 플러그인 원본의 upgrade 사용")
    if old.get("schema_version", 1) > SCHEMA:
        fail("새 버전 설정을 이전 도구로 갱신할 수 없음")
    default = read(plugin / "templates" / "feature.json")
    config = merge_defaults(old, default)
    if old and "commit_policy" not in old.get("loop", {}):
        config["loop"]["commit_policy"] = "auto" if old.get("loop", {}).get("auto_commit", True) else "manual"
    config.update(schema_version=SCHEMA, tool_version=VERSION, template_version=VERSION, work_dir=args.work_dir)
    manifest_path = work / "_templates" / ".manifest.json"
    manifest = read(manifest_path, {})
    new_manifest = dict(manifest)
    for source in (plugin / "templates").glob("*.md"):
        target = work / "_templates" / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and digest(target.read_bytes()) != manifest.get(source.name):
            candidate = target.with_name(target.name + ".incoming")
            candidate.write_bytes(source.read_bytes())
            print(f"사용자 템플릿 보존; 비교안: {candidate}")
        else:
            target.write_bytes(source.read_bytes())
            new_manifest[source.name] = digest(source.read_bytes())
    write(manifest_path, new_manifest)
    write(config_path, config)
    for source in (plugin / "templates").glob("runtime.*.json"):
        target = work / source.name
        defaults = read(source)
        if source.name == "runtime.claude.json" and old:
            defaults["agents"] = merge_defaults(old.get("agents", {}), defaults["agents"])
            defaults["default_model"] = old.get("default_model", defaults["default_model"])
        write(target, merge_defaults(read(target, {}), defaults))
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    for name in ("feature_status.py", "sdlc_runtime.py"):
        source, target = plugin / "scripts" / name, scripts / name
        if source.resolve() == target.resolve():
            continue
        if target.exists() and target.read_bytes() != source.read_bytes():
            backup = work / "_upgrades" / VERSION / name
            if not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(target.read_bytes())
        shutil.copyfile(source, target)
    if not (work / "groups.json").exists():
        write(work / "groups.json", {"schema_version": SCHEMA, "groups": []})
    API["ensure_gitignore"](root, config.get("worktree_dir", ".sdlc/worktrees").rstrip("/") + "/")
    print(f"{args.command}: {config_path}; 사용자 값 보존")


def migration_preflight(project):
    if git(project.root, "rev-parse", "HEAD", check=False) is None:
        fail("이전은 HEAD가 있는 Git 저장소만 지원")
    if git(project.root, "status", "--porcelain"):
        fail("이전 전 변경을 검토하고 커밋해야 함. 자동 stash하지 않음")
    if len(re.findall(r"^worktree ", git(project.root, "worktree", "list", "--porcelain"), re.M)) > 1:
        fail("별도 worktree가 있음: 보존된 실행을 정리한 뒤 이전")
    if git(project.root, "branch", "--list", "sdlc/*"):
        fail("보존된 sdlc 브랜치가 있음: 실행/초기화 상태를 먼저 확인")
    for path in status_paths(project):
        data = read(path)
        if data["phase"] in ("implementing", "validating", "blocked"):
            fail("진행 중 기능은 이전 미지원: " + data["feature"])
    if active_run(project):
        fail("활성 run 중 이전 금지")


def apply_journal(project, path, journal, rollback=False):
    def relocate(relative):
        for move in journal["moves"]:
            if relative == move["old"] or relative.startswith(move["old"] + "/"):
                return move["new"] + relative[len(move["old"]):]
        return relative
    if rollback:
        if groups(project) not in (journal["old_groups"], journal["new_groups"]):
            fail("이전 뒤 그룹 변경 감지: 복구 전 변경을 명시적으로 정리해야 함")
        if active_run(project):
            fail("활성 run 중 경로 복구 금지")
        for move in journal["moves"]:
            old, new = safe(project.root, move["old"]), safe(project.root, move["new"])
            if old.exists() and new.exists():
                fail(f"복구 경로 충돌: {old}, {new}")
            if not old.exists() and not new.exists():
                fail(f"복구할 경로 없음: {old}")
        # Validate every edited file before restoring any of them.
        for edit in journal["edits"]:
            target = safe(project.root, relocate(edit["path"]))
            if not target.exists():
                target = safe(project.root, edit["path"])
            if not target.exists() or target.read_text() not in (edit["old"], edit["new"]):
                fail(f"복구 전 추가 변경 또는 파일 누락: {target}")
        for edit in journal["edits"]:
            target = safe(project.root, relocate(edit["path"]))
            if not target.exists():
                target = safe(project.root, edit["path"])
            if target.exists() and target.read_text() not in (edit["old"], edit["new"]):
                fail(f"복구 전 추가 변경: {target}")
            if target.exists():
                target.write_text(edit["old"])
        for move in reversed(journal["moves"]):
            old, new = safe(project.root, move["old"]), safe(project.root, move["new"])
            if new.exists() and not old.exists():
                old.parent.mkdir(parents=True, exist_ok=True)
                new.rename(old)
        write(project.work_dir / "groups.json", journal["old_groups"])
        journal["state"] = "rolled_back"
    else:
        write(project.work_dir / "groups.json", journal["new_groups"])
        for move in journal["moves"]:
            old, new = safe(project.root, move["old"]), safe(project.root, move["new"])
            if old.exists() and new.exists():
                fail(f"양쪽 경로 존재: {old}, {new}")
            if old.exists():
                new.parent.mkdir(parents=True, exist_ok=True)
                old.rename(new)
            elif not new.exists():
                fail(f"이전 소스/대상 모두 없음: {old}")
        for edit in journal["edits"]:
            target = safe(project.root, relocate(edit["path"]))
            if target.read_text() not in (edit["old"], edit["new"]):
                fail(f"이전 도중 사용자 변경 감지: {target}")
            target.write_text(edit["new"])
        journal["state"] = "complete"
    write(path, journal)
    print(f"migration {journal['state']}: {path}")


def cmd_migrate(project, args):
    journal_path = project.work_dir / "_migrations" / "layout-v2.json"
    if args.resume or args.rollback:
        journal = read(journal_path)
        if not journal:
            fail("재개할 journal 없음")
        if args.dry_run:
            print(json.dumps(journal, ensure_ascii=False, indent=2))
        else:
            apply_journal(project, journal_path, journal, args.rollback)
        return
    unfinished = read(journal_path)
    if unfinished and unfinished["state"] == "pending":
        fail("미완료 이전: migrate --resume 또는 --rollback")
    mapping = read(Path(args.mapping), {}) if args.mapping else {}
    moves = []
    for path in status_paths(project):
        if path.parent.parent != project.work_dir:
            continue
        slug = path.parent.name
        gid = group_id(mapping.get(slug, slug.split("-", 1)[0]))
        target = project.work_dir / "groups" / gid / "features" / slug
        if target.exists():
            fail(f"대상 경로 존재: {target}")
        moves.append({"old": str(path.parent.relative_to(project.root)), "new": str(target.relative_to(project.root)), "group": gid})
    if not moves:
        print("이전할 평면 기능 없음")
        return
    migration_preflight(project)
    journal = migration_journal(project, moves)
    if args.dry_run:
        print(json.dumps({"moves": moves, "links_to_update": [e["path"] for e in journal["edits"]]}, ensure_ascii=False, indent=2))
        return
    write_migration(journal_path, journal)
    apply_journal(project, journal_path, journal)


def migration_journal(project, moves):
    def relocate(path):
        for move in moves:
            source = project.root / move["old"]
            if path == source or path.is_relative_to(source):
                return project.root / move["new"] / path.relative_to(source)
        return path
    edits = []
    candidates = [project.root / p for p in git(project.root, "ls-files", "-z").split("\0") if p.endswith(".md")]
    for path in candidates:
        relative = str(path.relative_to(project.root))
        if any(part in ("_runs", "_migrations", "_bootstrap", "_upgrades") for part in path.parts):
            continue
        old = path.read_text()
        destination = relocate(path)
        def link(match):
            raw = match[1]
            if re.match(r"(?:[A-Za-z]+:|/|#)", raw) or " " in raw:
                return match[0]
            name, separator, fragment = raw.partition("#")
            target = relocate((path.parent / name).resolve())
            if not target.is_relative_to(project.root):
                return match[0]
            updated = os.path.relpath(target, destination.parent)
            return "](" + updated + (separator + fragment if separator else "") + ")"
        new = re.sub(r"\]\(([^)]+)\)", link, old)
        for move in moves:
            new = new.replace(move["old"] + "/", move["new"] + "/")
        if old != new:
            edits.append({"path": relative, "old": old, "new": new})
    config_path = project.config_path
    old = config_path.read_text()
    new = old
    for move in moves:
        new = new.replace(move["old"], move["new"])
    if old != new:
        edits.append({"path": str(config_path.relative_to(project.root)), "old": old, "new": new})
    old_groups = groups(project)
    new_groups = copy.deepcopy(old_groups)
    for move in moves:
        if move["group"] not in new_groups["groups"]:
            new_groups["groups"].append(move["group"])
    return {"state": "pending", "at": stamp(), "base": git(project.root, "rev-parse", "HEAD"),
            "moves": moves, "edits": edits, "old_groups": old_groups, "new_groups": new_groups}


def cmd_move(project, args):
    old = resolve(project, args.slug)
    if args.group not in groups(project)["groups"]:
        fail("대상 그룹을 먼저 등록")
    new = project.work_dir / "groups" / args.group / "features" / args.slug
    if old == new:
        print("이미 해당 그룹")
        return
    if new.exists():
        fail("대상 폴더 충돌")
    migration_preflight(project)
    moves = [{"old": str(old.relative_to(project.root)), "new": str(new.relative_to(project.root)), "group": args.group}]
    journal = migration_journal(project, moves)
    if args.dry_run:
        print(json.dumps(moves, ensure_ascii=False))
        return
    path = project.work_dir / "_migrations" / "layout-v2.json"
    if read(path, {}).get("state") == "pending":
        fail("미완료 이전부터 재개")
    write_migration(path, journal)
    apply_journal(project, path, journal)


def common_dir(root):
    location = git(root, "rev-parse", "--git-common-dir", check=False)
    return (root / location).resolve() if location else None


def active_run(project):
    common = common_dir(project.root)
    if not common:
        return None
    pointer = read(common / "sdlc-active.json")
    if not pointer:
        return None
    path = Path(pointer["record"])
    if not path.exists():
        if pointer.get("initial_record"):
            return path, {**pointer["initial_record"], "state": "starting"}
        fail(f"활성 run 포인터에 기록이 없음: {path}; 보존 브랜치/워크트리 조사 필요")
    return path, read(path)


def cmd_run(project, args):
    active = active_run(project)
    if args.action == "show":
        print(json.dumps(active[1] if active else {}, ensure_ascii=False, indent=2))
        return
    if args.action == "start":
        if active:
            fail("활성 run을 먼저 재개: " + str(active[0]))
        if not args.features:
            fail("--features ID,ID 필요")
        features = API["split_ids"](args.features)
        if len(set(features)) != len(features):
            fail("중복 기능 범위")
        _, queue = API["load_queue"](project)
        API["validate_queue"](queue["items"])
        queued = [i["feature"] for i in queue["items"] if i["feature"] in features]
        if queued != features:
            fail("승인 범위는 큐 순서를 따라야 함")
        for slug in features:
            path, data = project.load(slug)
            if data["phase"] != "review":
                fail(f"새 run은 review 기능만: {slug}; 미완료 run 재개/legacy 재검증 필요")
            if sync_result(project, path.parent / "plan.md", data) != data["steps"]:
                fail(f"plan 동기화 필요: {slug}")
        for item in queue["items"]:
            if item["feature"] not in features:
                continue
            for dep in item.get("depends_on", []):
                if dep not in features:
                    _, data = project.load(dep)
                    if project.phase_of(dep) != "done" or completion_errors(project, dep, data):
                        fail(f"범위 밖 선행 기능 미검증: {dep}")
        if git(project.root, "status", "--porcelain"):
            fail("run 시작 전 문서/설정 변경을 검토하고 커밋 필요")
        base = git(project.root, "branch", "--show-current")
        if not base:
            fail("detached HEAD에서 시작 불가")
        run_id = args.slug if args.slug != "_" else stamp().replace(":", "").replace("+", "-")
        group_id(run_id.replace("T", "t"))
        branch = f"sdlc/batch-{run_id}"
        workspace = safe(project.root, Path(project.config.get("worktree_dir", ".sdlc/worktrees")) / f"batch-{run_id}")
        if workspace.exists() or git(project.root, "rev-parse", "--verify", branch, check=False):
            fail("기존 배치 경로/브랜치 충돌")
        pointer_path = common_dir(project.root) / "sdlc-active.json"
        record_path = workspace / project.work_dir.relative_to(project.root) / "_runs" / run_id / "run.json"
        record = {"id": run_id, "state": "implementing", "features": features, "target": base,
                  "base_sha": git(project.root, "rev-parse", "HEAD"), "base_root": str(project.root),
                  "branch": branch, "workspace": str(workspace), "work_dir": str(project.work_dir.relative_to(project.root)),
                  "engine": args.engine, "approved_at": stamp(), "policy": copy.deepcopy(project.config.get("loop", {})),
                  "specs": {slug: snapshot(project, slug)["spec_hash"] for slug in features}, "ready": {}}
        # Keep the approved initial record outside the new worktree for crash recovery.
        with pointer_path.open("x") as handle:
            json.dump({"record": str(record_path), "branch": branch, "initial_record": record}, handle)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            git(project.root, "worktree", "add", "-b", branch, str(workspace), "HEAD")
            write(record_path, record)
            if record["policy"].get("commit_policy", "auto") == "auto":
                git(workspace, "add", str(record_path.relative_to(workspace)))
                git(workspace, "commit", "-m", f"sdlc: run {run_id} 승인 기록")
        except BaseException:
            # Keep a discoverable pointer if a workspace was successfully created.
            if not workspace.exists():
                pointer_path.unlink(missing_ok=True)
            raise
        print(workspace)
        return
    if not active:
        fail("활성 run 없음")
    path, run = active
    workspace = Path(run["workspace"])
    if args.action == "recover-start":
        if run["state"] != "starting":
            fail("시작 복구 대상이 아님")
        if not workspace.exists() or git(workspace, "branch", "--show-current") != run["branch"]:
            fail("시작 worktree/브랜치 확인 필요. 파일을 보존하고 복구")
        if common_dir(workspace) != common_dir(project.root):
            fail("다른 저장소의 worktree")
        run["state"] = "implementing"
        write(path, run)
        print("시작 기록 복구. 검토 후 승인 기록을 커밋하고 재개")
        return
    if run["state"] == "starting" and args.action != "abandon":
        fail("중단된 시작: run _ recover-start로 기록 복구")
    batch = API["Project"](workspace, run["work_dir"])
    if args.action == "abandon":
        if not args.note:
            fail("중단 이유 필요")
        run.update(state="abandoned", note=args.note)
        write(path, run)
        (common_dir(project.root) / "sdlc-active.json").unlink()
        print("작업 브랜치/파일 보존. 다시 구현하려면 보존 run 조사 후 수동 복구")
        return
    if args.action == "review":
        if not args.evidence or not args.model or not args.effort or not args.independent:
            fail("독립 리뷰의 --evidence, --model, --effort, --independent 필요")
        evidence = safe(workspace, args.evidence)
        if not evidence.is_file():
            fail("리뷰 결과 파일 없음")
        if run.get("engine") == "codex":
            expected = read(batch.work_dir / "runtime.codex.json", {}).get("profiles", {}).get("review")
            if not expected or (args.model, args.effort) != (expected["model"], expected["effort"]):
                fail("설정된 Codex 리뷰 모델/추론 수준과 다름")
        run["review"] = {"result": args.result, "evidence": str(evidence.relative_to(workspace)),
                         "model": args.model, "effort": args.effort, "independent": True,
                         "at": stamp(), "inputs": {slug: snapshot(batch, slug) for slug in run["features"]}}
        write(path, run)
        print("독립 리뷰 기록")
        return
    if args.action == "ready":
        slug = args.feature
        if slug not in run["features"]:
            fail("run 범위 밖 기능")
        # Called from the feature worktree before integration into the batch.
        _, data = project.load(slug)
        if data["phase"] not in ("implementing", "validating"):
            fail("구현한 기능만 배치 통합 가능")
        if not data["steps"] or any(s["status"] != "done" for s in data["steps"]):
            fail("작업 미완료")
        if snapshot(project, slug)["spec_hash"] != run["specs"][slug]:
            fail("승인 이후 명세 변경: run accept-spec 필요")
        errors = proof_errors(project, slug, data, contract_only=True)
        if errors:
            fail("선행 계약 미검증: " + "; ".join(errors))
        if not isinstance(run.get("ready"), dict):
            run["ready"] = {}
        run["ready"][slug] = {"inputs": snapshot(project, slug), "at": stamp()}
        write(path, run)
        print("기능 계약 검증 충족; 배치 브랜치에 통합 가능")
        return
    if args.action == "accept-spec":
        if not args.note or args.feature not in run["features"]:
            fail("--feature와 명세 변경 합의 근거 --note 필요")
        run["specs"][args.feature] = snapshot(project, args.feature)["spec_hash"]
        run.setdefault("decisions", []).append({"feature": args.feature, "note": args.note, "at": stamp()})
        write(path, run)
        return
    if args.action == "refresh-base":
        current = git(Path(run["base_root"]), "rev-parse", run["target"])
        if git(workspace, "merge-base", "--is-ancestor", current, "HEAD", check=False) is None:
            fail("먼저 기준 브랜치를 배치에 통합하고 다시 검증")
        run["base_sha"] = current
        run["state"] = "validating"
        write(path, run)
        print("기준 SHA 갱신. 통합 결과에서 proof 재확인 필요")
        return
    if args.action == "finish":
        root = Path(run["base_root"])
        if git(root, "branch", "--show-current") != run["target"]:
            fail("기준 worktree의 현재 브랜치가 바뀜")
        if run.get("state") == "done":
            if git(root, "status", "--porcelain"):
                fail("완료 기록 커밋 대기: 기준 트리에서 검토·커밋 후 재개")
            target = API["Project"](root, run["work_dir"])
            saved = read(target.work_dir / "_runs" / run["id"] / "run.json", {})
            if saved.get("state") != "done" or saved.get("merged_sha") != run["merged_sha"]:
                fail("기준 트리에 완료 기록 없음: 삭제/취소된 기록 복구 필요")
            for slug in run["features"]:
                _, data = target.load(slug)
                integration = data.get("integration", {})
                if (data["phase"] != "done" or integration.get("run") != run["id"]
                        or integration.get("revision") != run["merged_sha"]
                        or any(integration.get(key) != value for key, value in snapshot(target, slug).items())
                        or snapshot(target, slug)["spec_hash"] != run["specs"][slug]
                        or completion_errors(target, slug, data)):
                    fail(f"완료 기록 또는 검증 입력 변경: {slug}")
            if run.get("engine") == "codex" and run.get("review", {}).get("inputs") != {slug: snapshot(target, slug) for slug in run["features"]}:
                fail("완료 이후 독립 리뷰 입력 변경")
            (common_dir(root) / "sdlc-active.json").unlink()
            print("완료 기록 확인")
            return
        if run.get("state") == "merging" and git(root, "merge-base", "--is-ancestor", run["merged_sha"], "HEAD", check=False) is not None:
            run["state"] = "integrated"
        if run.get("state") == "integrated":
            # Recover a crash after merge, before completion records were committed.
            if git(root, "merge-base", "--is-ancestor", run["merged_sha"], "HEAD", check=False) is None:
                fail("기록된 통합 커밋이 기준 브랜치에 없음")
        else:
            if run.get("engine") == "codex":
                review = run.get("review", {})
                inputs = {slug: snapshot(batch, slug) for slug in run["features"]}
                if review.get("result") != "pass" or not review.get("independent") or review.get("inputs") != inputs:
                    fail("Codex 독립 리뷰 미완료/실패/stale: 지정 review 모델의 검토 필요")
            if git(root, "rev-parse", "HEAD") != run["base_sha"]:
                fail("기준 HEAD 변경: 배치에 통합 후 run refresh-base와 재검증 필요")
            for slug in run["features"]:
                _, data = batch.load(slug)
                if snapshot(batch, slug)["spec_hash"] != run["specs"][slug]:
                    fail(f"승인 명세 변경: {slug}")
                errors = completion_errors(batch, slug, data)
                if errors:
                    fail(f"{slug}: " + "; ".join(errors))
            run["state"] = "awaiting_merge"
            write(path, run)
            if git(workspace, "status", "--porcelain"):
                if run["policy"].get("commit_policy", "auto") == "manual":
                    print("커밋 대기: 배치 변경을 커밋 후 run finish 재호출")
                    return
                git(workspace, "add", "--", run["work_dir"])
                git(workspace, "commit", "-m", "sdlc: 배치 검증 기록")
            if git(workspace, "status", "--porcelain"):
                fail("배치에 미커밋 구현 변경이 있음: 검토·검증·커밋 필요")
            if run["policy"].get("merge_policy") == "manual" and not args.merge:
                print("병합 대기: 검토 후 run finish --merge")
                return
            if git(root, "status", "--porcelain"):
                fail("기준 트리 변경을 보존하고 병합 중단")
            # --ff-only gives the exact tested tree; base drift was checked above.
            merged = git(workspace, "rev-parse", "HEAD")
            run.update(state="merging", merged_sha=merged, merged_inputs={slug: snapshot(batch, slug) for slug in run["features"]})
            write(path, run)
            git(root, "merge", "--ff-only", merged)
            run["state"] = "integrated"
            write(path, run)
        target = API["Project"](root, run["work_dir"])
        for slug in run["features"]:
            if (snapshot(target, slug) != run.get("merged_inputs", {}).get(slug)
                    or snapshot(target, slug)["spec_hash"] != run["specs"][slug]):
                fail(f"통합된 코드/승인 명세 이후 입력 변경: {slug}")
            status_path, data = target.load(slug)
            if completion_errors(target, slug, data):
                fail(f"통합 결과 재검증 필요: {slug}")
            data["integration"] = {"run": run["id"], "revision": run["merged_sha"], **snapshot(target, slug)}
            data["phase"] = "done"
            API["add_note"](data, "단계 → done: 배치 검증 및 통합 완료")
            API["save"](status_path, data)
        run.update(state="done", completed_at=stamp())
        write(target.work_dir / "_runs" / run["id"] / "run.json", run)
        write(path, run)
        if run["policy"].get("commit_policy") == "manual":
            print("통합 완료, 완료 기록 커밋 대기. 기준 트리에서 커밋 후 run finish 재호출")
            return
        git(root, "add", "--", run["work_dir"])
        git(root, "commit", "-m", "sdlc: 배치 완료 기록")
        (common_dir(root) / "sdlc-active.json").unlink()
        print("완료. 배치/기능 worktree는 검토 후 명시적으로 정리한다.")


def bootstrap_records(root, work_dir):
    candidates = [root]
    top = git(root, "rev-parse", "--show-toplevel", check=False)
    if top and Path(top).resolve() == root:
        listing = git(root, "worktree", "list", "--porcelain", check=False) or ""
        candidates += [Path(line[9:]) for line in listing.splitlines() if line.startswith("worktree ")]
    records = {}
    for candidate in set(candidates):
        for path in (candidate / work_dir / "_bootstrap").glob("*/bootstrap.json"):
            record = read(path)
            records[(record.get("workspace"), record.get("id"))] = record
    return list(records.values())


def cmd_bootstrap(args):
    root = Path(args.root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.action == "show":
        print(json.dumps(bootstrap_records(root, args.work_dir), ensure_ascii=False, indent=2))
        return
    identifier = group_id(args.id)
    config = read(root / args.work_dir / "feature.json", {})
    directory = config.get("constitution_dir", "specs")
    safe(root, directory)
    if args.action == "finish":
        record_path = root / args.work_dir / "_bootstrap" / identifier / "bootstrap.json"
        record = read(record_path)
        if not record:
            fail("bootstrap 기록 없음: 해당 worktree에서 실행")
        for name in ("mission.md", "tech-stack.md", "roadmap.md"):
            path = safe(root, Path(directory) / name)
            if not path.is_file() or len(path.read_text().strip()) < 30:
                fail(f"문서가 비어 있음: {name}")
        if not config:
            fail("먼저 플러그인 setup으로 도구 설치")
        docs = [str(Path(directory) / name) for name in ("mission.md", "tech-stack.md", "roadmap.md")]
        config["big_picture_docs"] = list(dict.fromkeys(docs + config.get("big_picture_docs", [])))
        config["milestone_table"] = docs[2]
        config.setdefault("constraint_sources", [docs[1]])
        write(root / args.work_dir / "feature.json", config)
        record["state"] = "review"
        write(record_path, record)
        print("문서/설정 연결 완료. 내용 검토 후 기준 브랜치에 반영")
        return
    pending = [record for record in bootstrap_records(root, args.work_dir)
               if record.get("mode") == args.mode and record.get("state") != "completed"]
    if pending:
        if len(pending) > 1:
            fail("여러 초기화 기록 존재: bootstrap show로 확인 후 재개 대상 지정")
        if pending[0]["id"] != identifier:
            fail("동일 모드 초기화 진행 중: " + str(pending[0]["workspace"]) + "; 기존 ID로 재개")
        print(pending[0]["workspace"])
        return
    toplevel = git(root, "rev-parse", "--show-toplevel", check=False)
    head = git(root, "rev-parse", "HEAD", check=False) if toplevel and Path(toplevel).resolve() == root else None
    branch = f"sdlc/{args.mode}-{identifier}"
    work = root
    if head:
        work = safe(root, Path(config.get("worktree_dir", ".sdlc/worktrees")) / f"{args.mode}-{identifier}")
        if work.exists():
            record = read(work / args.work_dir / "_bootstrap" / identifier / "bootstrap.json")
            if not record or record["mode"] != args.mode:
                fail("기존 worktree가 다른 초기화에 속함")
            print(work)
            return
        # Local Git exclusion avoids changing/stashing the user's dirty tree.
        exclude = common_dir(root) / "info" / "exclude"
        exclude.parent.mkdir(parents=True, exist_ok=True)
        text = exclude.read_text() if exclude.exists() else ""
        ignore = config.get("worktree_dir", ".sdlc/worktrees").rstrip("/") + "/"
        if ignore not in text.splitlines():
            exclude.write_text(text + "\n" + ignore + "\n")
        git(root, "worktree", "add", "-b", branch, str(work), head)
    record_path = safe(work, Path(args.work_dir) / "_bootstrap" / identifier / "bootstrap.json")
    if record_path.exists():
        print(work)
        return
    record = {"id": identifier, "mode": args.mode, "state": "interview", "base_sha": head,
              "source_root": str(root), "workspace": str(work), "branch": branch if head else None,
              "sources": [], "decisions": [], "questions": [], "at": stamp()}
    write(record_path, record)
    print(work)


def cmd_runtime(project, args):
    path = project.work_dir / f"runtime.{args.slug}.json"
    data = read(path)
    if not data:
        fail(f"실행 설정 없음: {path}; 해당 엔진 플러그인의 upgrade 필요")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_changelog(project, args):
    records = []
    for path in status_paths(project):
        data = read(path)
        if data["phase"] == "done" and data.get("integration"):
            records.append((data["feature"], data["integration"]["revision"]))
    text = "# 변경 기록\n\n" + "\n".join(f"- {slug} · `{revision}`" for slug, revision in sorted(records)) + "\n"
    if args.write:
        target = project.root / "CHANGELOG.md"
        start, end = "<!-- sdlc:start -->", "<!-- sdlc:end -->"
        block = start + "\n" + text + end
        old = target.read_text() if target.exists() else ""
        new = re.sub(re.escape(start) + r"[\s\S]*?" + re.escape(end), lambda _: block, old) if start in old else old + "\n" + block + "\n"
        target.write_text(new)
    else:
        print(text)


def register(parser, sub, api):
    bind(api)
    commands = sub.choices
    for name, fn in {"setup": cmd_setup, "init": cmd_init, "phase": cmd_phase, "step": cmd_step,
                     "proof": cmd_proof, "sync-plan": cmd_sync}.items():
        commands[name].set_defaults(func=fn)
    commands["init"].add_argument("--group")
    for name in ("list", "report", "queue"):
        commands[name].add_argument("--group")
    for flag in ("evidence", "actor"):
        commands["proof"].add_argument("--" + flag, default="orchestrator" if flag == "actor" else None)
    commands["proof"].add_argument("--exit-code", type=int)
    p = sub.add_parser("upgrade", help="플러그인 원본에서 프로젝트 도구 갱신(사용자 설정 보존)")
    p.add_argument("root", nargs="?", default=".")
    p.add_argument("--work-dir", default="docs/work")
    p.set_defaults(func=cmd_setup, needs_project=False)
    for name, fn in (("resolve", cmd_resolve), ("resolve-path", cmd_resolve_path), ("check-plan", cmd_sync), ("check", cmd_check),
                     ("complete", cmd_phase), ("invalidate", cmd_invalidate), ("reopen", cmd_reopen), ("doctor", cmd_doctor)):
        p = sub.add_parser(name)
        p.add_argument("slug", nargs="?" if name == "doctor" else None)
        p.add_argument("--note", required=name in ("invalidate", "reopen"))
        p.set_defaults(func=fn, needs_project=True)
    p = sub.add_parser("runtime")
    p.add_argument("slug", choices=("claude", "codex"))
    p.set_defaults(func=cmd_runtime, needs_project=True)
    p = sub.add_parser("retire-step")
    p.add_argument("slug")
    p.add_argument("id")
    p.add_argument("--note", required=True)
    p.set_defaults(func=cmd_retire, needs_project=True)
    p = sub.add_parser("group")
    p.add_argument("slug")
    p.add_argument("action", choices=("add", "show"))
    p.set_defaults(func=cmd_group, needs_project=True)
    p = sub.add_parser("move")
    p.add_argument("slug")
    p.add_argument("--group", required=True)
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_move, needs_project=True)
    p = sub.add_parser("migrate")
    p.add_argument("slug", nargs="?", default="_")
    p.add_argument("--mapping")
    p.add_argument("--dry-run", action="store_true")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--resume", action="store_true")
    mode.add_argument("--rollback", action="store_true")
    p.set_defaults(func=cmd_migrate, needs_project=True)
    p = sub.add_parser("run")
    p.add_argument("slug")
    p.add_argument("action", choices=("start", "show", "ready", "refresh-base", "finish", "accept-spec", "abandon", "review", "recover-start"))
    p.add_argument("--features")
    p.add_argument("--engine", choices=("claude", "codex"), default="claude")
    p.add_argument("--evidence")
    p.add_argument("--model")
    p.add_argument("--effort")
    p.add_argument("--independent", action="store_true")
    p.add_argument("--result", choices=("pass", "fail"), default="pass")
    p.add_argument("--feature")
    p.add_argument("--note")
    p.add_argument("--merge", action="store_true")
    p.set_defaults(func=cmd_run, needs_project=True)
    p = sub.add_parser("bootstrap")
    p.add_argument("action", choices=("start", "show", "finish"))
    p.add_argument("--root", default=".")
    p.add_argument("--work-dir", default="docs/work")
    p.add_argument("--mode", choices=("init", "adopt"), default="init")
    p.add_argument("--id", default="foundation")
    p.set_defaults(func=cmd_bootstrap, needs_project=False)
    p = sub.add_parser("changelog")
    p.add_argument("slug", nargs="?", default="_")
    p.add_argument("--write", action="store_true")
    p.set_defaults(func=cmd_changelog, needs_project=True)
