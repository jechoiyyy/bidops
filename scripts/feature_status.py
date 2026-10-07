"""기능 문서 사이클(intent → spec → plan → 구현)의 진행 상태를 관리하는 범용 스크립트.

프로젝트별 값은 `<work_dir>/feature.json`에서 읽는다. 상태의 원본은
`<work_dir>/groups/<group>/features/<기능 ID>/status.json` 하나이며, 상태 값은 고정 enum만 쓴다.
- phase: drafting / review / implementing / validating / done / blocked
- steps[].status: pending / in_progress / done / blocked
- steps[].model: 설정 agents의 키(plan.md 작업 순서 항목 끝의 `[모델]` 태그)
- proof.*: pending / pass / fail / skipped   (키는 설정의 proof에서 정한다)

기능 사이의 실행 순서와 의존은 `<work_dir>/queue.json` 하나에 둔다(`queue` 명령).
불변식: depends_on의 항목은 큐에서 더 앞에 있어야 한다(따라서 순환이 생길 수 없다).
상태는 큐에 저장하지 않고 각 status.json에서 읽는다.

`setup` 명령은 이 스크립트와 템플릿, 기본 설정을 대상 프로젝트로 복사한다.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_WORK_DIR = "docs/work"
CONFIG_NAME = "feature.json"
QUEUE_NAME = "queue.json"
PHASES = ("drafting", "review", "implementing", "validating", "done", "blocked")
STEP_STATUSES = ("pending", "in_progress", "done", "blocked", "stale")
PROOF_STATUSES = ("pending", "pass", "fail", "skipped", "not_applicable", "stale")
STEPS_HEADING_DEFAULT = "## 작업 순서"
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}
TAG_RE = re.compile(r"\s*\[([^\]]+)\]\s*$")


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def find_root(start: Path) -> Path:
    """`.git` 또는 설정 파일이 있는 상위 디렉터리를 프로젝트 루트로 본다."""
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists() or (candidate / DEFAULT_WORK_DIR / CONFIG_NAME).exists():
            return candidate
    here = Path(__file__).resolve().parent.parent
    return here if (here / "scripts" / "feature_status.py").exists() else start


def discover_work_dir(root: Path) -> Path:
    """기본 위치에 설정이 없으면 루트 아래 깊이 3까지 feature.json을 찾는다. 하나여야 한다."""
    default = root / DEFAULT_WORK_DIR
    if (default / CONFIG_NAME).exists():
        return default
    found: list[Path] = []
    for pattern in ("*/", "*/*/", "*/*/*/"):
        for directory in root.glob(pattern):
            parts = directory.relative_to(root).parts
            if any(part in SKIP_DIRS or part.startswith(".") for part in parts):
                continue
            if (directory / CONFIG_NAME).exists():
                found.append(directory)
    if len(found) == 1:
        return found[0]
    if not found:
        sys.exit(f"설정 없음: {default / CONFIG_NAME}. 먼저 `setup`을 실행하거나 --work-dir를 지정한다.")
    sys.exit("설정이 여러 개다. --work-dir로 하나를 지정한다: " + ", ".join(str(f) for f in found))


class Project:
    def __init__(self, root: Path, work_dir: str | None = None) -> None:
        self.root = root.resolve()
        self.work_dir = root / work_dir if work_dir else discover_work_dir(root)
        self.work_dir = runtime.safe(self.root, self.work_dir)
        self.config_path = self.work_dir / CONFIG_NAME
        if not self.config_path.exists():
            sys.exit(f"설정 없음: {self.config_path}. 먼저 `setup`을 실행한다.")
        self.config = json.loads(self.config_path.read_text(encoding="utf-8"))
        if self.config.get("schema_version", 1) > runtime.SCHEMA:
            raise ValueError("새 schema: 도구 upgrade 필요")
        self.id_re = re.compile(self.config["id_pattern"])
        self.proof_keys = tuple(self.config["proof"].keys())
        self.agents = self.config.get("agents", {})
        self.default_model = self.config.get("default_model")
        self.steps_heading = self.config.get("steps_heading", STEPS_HEADING_DEFAULT)

    def feature_dir(self, slug: str) -> Path:
        return runtime.resolve(self, slug)

    def load(self, slug: str) -> tuple[Path, dict]:
        path = self.feature_dir(slug) / "status.json"
        if not path.exists():
            sys.exit(f"status.json 없음: {path}")
        return path, json.loads(path.read_text(encoding="utf-8"))

    def phase_of(self, slug: str) -> str:
        try:
            _, data = self.load(slug)
        except FileNotFoundError:
            return "없음"
        if data.get("phase") == "done" and data.get("schema_version", 1) < 2:
            return "legacy_unverified"
        if data.get("phase") == "done" and runtime.completion_errors(self, slug, data):
            return "validating"
        return data.get("phase", "없음")

    def status_paths(self, group=None):
        return runtime.status_paths(self, group)


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".sdlc-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def save(path: Path, data: dict) -> None:
    data["updated_at"] = now()
    atomic_json(path, data)


def add_note(data: dict, text: str | None) -> None:
    if text:
        data["notes"].append({"at": now(), "text": text})


# --- setup -----------------------------------------------------------------


WORKTREE_IGNORE = ".claude/worktrees/"


def ensure_gitignore(root: Path, line: str) -> None:
    """루프가 기능별 worktree를 두는 폴더를 .gitignore에 넣는다. 이미 있으면 그대로."""
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    if line in (l.strip() for l in existing):
        return
    text = "\n".join(existing).rstrip("\n")
    text = (text + "\n" if text else "") + f"# /sdlc:loop 기능별 worktree\n{line}\n"
    path.write_text(text, encoding="utf-8")
    print(f".gitignore에 추가: {line}")


# --- 상태 명령 ---------------------------------------------------------------


def cmd_config(project: Project, args: argparse.Namespace) -> None:
    print(json.dumps(project.config, ensure_ascii=False, indent=2))


def format_step(step: dict) -> str:
    mark = {"done": "x", "in_progress": ">", "blocked": "!"}.get(step["status"], " ")
    model = f" @{step['model']}" if step.get("model") else ""
    return f"  [{mark}] {step['id']}. {step['title']}{model} ({step['status']})"


def cmd_show(project: Project, args: argparse.Namespace) -> None:
    _, data = project.load(args.slug)
    print(f"기능: {data['feature']}  단계: {project.phase_of(args.slug)}  갱신: {data['updated_at']}")
    if data["steps"]:
        print("작업 순서:")
        for step in data["steps"]:
            print(format_step(step))
    print("증명: " + ", ".join(f"{k}={runtime.result(v)}" for k, v in data["proof"].items()))
    for note in data["notes"][-5:]:
        print(f"  메모 {note['at']}: {note['text']}")


def cmd_list(project: Project, args: argparse.Namespace) -> None:
    rows = []
    for path in project.status_paths(getattr(args, "group", None)):
        data = json.loads(path.read_text(encoding="utf-8"))
        done = sum(1 for s in data["steps"] if s["status"] == "done")
        rows.append((data["feature"], project.phase_of(data["feature"]), f"{done}/{len(data['steps'])}", data["updated_at"] or "-"))
    if not rows:
        print("기능 없음")
        return
    width = max(len(r[0]) for r in rows)
    for feature, phase, progress, updated in rows:
        print(f"{feature.ljust(width)}  {phase.ljust(12)}  단계 {progress.rjust(5)}  {updated}")


def phase_times(data: dict) -> dict[str, str]:
    """메모에서 각 단계에 처음 들어간 시각을 뽑는다."""
    times: dict[str, str] = {}
    for note in data["notes"]:
        text = note["text"]
        if text.startswith("생성"):
            times.setdefault("drafting", note["at"])
        elif text.startswith("단계 → "):
            phase = text[len("단계 → "):].split(":", 1)[0].strip()
            times.setdefault(phase, note["at"])
    return times


def hours_between(a: str | None, b: str | None) -> str:
    if not a or not b:
        return "-"
    delta = datetime.fromisoformat(b) - datetime.fromisoformat(a)
    return f"{delta.total_seconds() / 3600:.1f}h"


def cmd_report(project: Project, args: argparse.Namespace) -> None:
    """회고용 요약. 완료(done) 기능을 기본으로, --all이면 전부, --features면 지정 기능만(단계 무관)."""
    wanted = split_ids(args.features) if args.features else None
    rows = []
    for path in project.status_paths(getattr(args, "group", None)):
        data = json.loads(path.read_text(encoding="utf-8"))
        if wanted is not None:
            if data["feature"] not in wanted:
                continue
        elif not args.all and data["phase"] != "done":
            continue
        times = phase_times(data)
        notes = [n["text"] for n in data["notes"]]
        blocked = sum(1 for n in notes if "blocked" in n)
        retries = sum(1 for n in notes if "재시도" in n or "재전송" in n)
        concerns = sum(1 for s in data["steps"] if s.get("note"))
        proof = ", ".join(f"{k}={runtime.result(v)}" for k, v in data["proof"].items() if runtime.result(v) != "pass")
        rows.append(
            (
                data["feature"],
                project.phase_of(data["feature"]),
                str(len(data["steps"])),
                hours_between(times.get("drafting"), times.get("implementing")),
                hours_between(times.get("implementing"), times.get("done")),
                str(blocked),
                str(retries),
                str(concerns),
                proof or "모두 pass",
            )
        )
    if not rows:
        print("보고할 기능 없음")
        return
    header = ("기능", "단계", "작업 수", "문서 소요", "구현 소요", "차단", "재시도", "우려 메모", "증명(비pass)")
    print("| " + " | ".join(header) + " |")
    print("|" + "---|" * len(header))
    for row in rows:
        print("| " + " | ".join(row) + " |")


# --- 큐(기능 사이의 실행 순서·의존) -----------------------------------------------


def split_ids(text: str | None) -> list[str]:
    """쉼표 구분 기능 ID 목록. 빈 문자열은 빈 목록."""
    return [t.strip() for t in (text or "").split(",") if t.strip()]


def load_queue(project: Project) -> tuple[Path, dict]:
    path = project.work_dir / QUEUE_NAME
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    data.setdefault("items", [])
    return path, data


def save_queue(path: Path, data: dict) -> None:
    atomic_json(path, data)


def validate_queue(items: list[dict]) -> None:
    """중복 없음, depends_on은 큐 안에 있고 더 앞에 위치. 위반이면 종료."""
    features = [item["feature"] for item in items]
    if len(set(features)) != len(features):
        sys.exit("큐에 같은 기능이 두 번 있다.")
    for idx, item in enumerate(items):
        for dep in item.get("depends_on", []):
            if dep == item["feature"]:
                sys.exit(f"자기 자신에 의존: {dep}")
            if dep not in features:
                sys.exit(f"{item['feature']}의 선행 기능 {dep}이 큐에 없다. 먼저 `queue {dep} add`.")
            if features.index(dep) > idx:
                sys.exit(f"{item['feature']}의 선행 기능 {dep}이 큐에서 뒤에 있다. 순서를 바꾼다(`queue ... move`).")


def queue_position(items: list[dict], args: argparse.Namespace, default_end: bool = True) -> int:
    """--first / --after ID / --last 로 삽입 위치를 정한다."""
    if getattr(args, "first", False):
        return 0
    if getattr(args, "after", None):
        features = [item["feature"] for item in items]
        if args.after not in features:
            sys.exit(f"--after 대상 {args.after}이 큐에 없다.")
        return features.index(args.after) + 1
    return len(items)


def matches_prefix(feature: str, prefix: str) -> bool:
    """접두어는 ID 구성 요소 경계에서만 맞는다(M2는 M2-01-x에 맞고 M20-...에는 안 맞음)."""
    return feature == prefix or feature.startswith(prefix + "-")


def cmd_queue(project: Project, args: argparse.Namespace) -> None:
    path, data = load_queue(project)
    items: list[dict] = data["items"]
    features = [item["feature"] for item in items]
    action = args.action

    if action == "show":
        if not items:
            print("큐 비어 있음")
            return
        width = max(len(f) for f in features)
        print(f"{'#':>2}  {'기능'.ljust(width)}  {'단계'.ljust(12)}  {'진행'.rjust(5)}  선행 기능(충족)")
        for idx, item in enumerate(items, start=1):
            if args.group and runtime.feature_group(project, item["feature"]) != args.group:
                continue
            phase = project.phase_of(item["feature"])
            status_path = project.feature_dir(item["feature"]) / "status.json"
            progress = "-"
            if status_path.exists():
                steps = json.loads(status_path.read_text(encoding="utf-8"))["steps"]
                progress = f"{sum(1 for s in steps if s['status'] == 'done')}/{len(steps)}"
            deps = item.get("depends_on", [])
            dep_text = ", ".join(f"{d}({'o' if project.phase_of(d) == 'done' else 'x'})" for d in deps) or "-"
            print(f"{idx:>2}  {item['feature'].ljust(width)}  {phase.ljust(12)}  {progress.rjust(5)}  {dep_text}")
        return

    if action == "next":
        ids = split_ids(args.ids)
        missing = [i for i in ids if i not in features]
        if missing:
            sys.exit("큐에 없는 기능: " + ", ".join(missing))
        scope = [
            item for item in items
            if project.phase_of(item["feature"]) != "done"
            and (not args.prefix or matches_prefix(item["feature"], args.prefix))
            and (not ids or item["feature"] in ids)
            and (not args.group or runtime.feature_group(project, item["feature"]) == args.group)
        ]
        scope_ids = [item["feature"] for item in scope]
        problems = []
        for item in scope:
            for dep in item.get("depends_on", []):
                if dep not in scope_ids and project.phase_of(dep) != "done":
                    problems.append(f"{item['feature']} ← {dep} ({project.phase_of(dep)})")
        if problems:
            sys.exit("범위 밖 미완료 선행 기능:\n  " + "\n  ".join(problems))
        for feature in scope_ids:
            print(feature)
        return

    slug = args.slug
    if not project.id_re.match(slug):
        sys.exit(f"기능 ID 형식 오류: {slug} (예: {project.config.get('id_example', '')})")

    if action == "add":
        project.load(slug)  # status.json이 있어야 한다
        if slug in features:
            sys.exit(f"이미 큐에 있음: {slug} (위치를 바꾸려면 `move`)")
        item = {"feature": slug, "depends_on": split_ids(args.depends_on), "added_at": now()}
        items.insert(queue_position(items, args), item)
        validate_queue(items)
        save_queue(path, data)
        print(f"큐 등록: {slug} (#{[i['feature'] for i in items].index(slug) + 1}/{len(items)})")
        return

    if slug not in features:
        sys.exit(f"큐에 없음: {slug}")
    index = features.index(slug)

    if action == "move":
        if not (args.first or args.last or args.after):
            sys.exit("move에는 --first, --last, --after ID 중 하나가 필요하다.")
        item = items.pop(index)
        items.insert(queue_position(items, args), item)
        validate_queue(items)
        save_queue(path, data)
        print(f"이동: {slug} → #{[i['feature'] for i in items].index(slug) + 1}/{len(items)}")
        return

    if action == "remove":
        items.pop(index)
        validate_queue(items)
        save_queue(path, data)
        print(f"큐 제거: {slug}")
        return

    if action == "depends":
        if args.set is None:
            sys.exit("depends에는 --set A,B (빈 문자열이면 의존 없음)가 필요하다.")
        items[index]["depends_on"] = split_ids(args.set)
        validate_queue(items)
        save_queue(path, data)
        print(f"선행 기능: {slug} ← {', '.join(items[index]['depends_on']) or '없음'}")
        return

    sys.exit(f"모르는 queue 동작: {action}")


# --- CLI -------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="기능 문서 사이클 상태 관리")
    parser.add_argument("--root", help="프로젝트 루트(기본: .git 또는 설정 파일을 찾아 자동 결정)")
    parser.add_argument("--work-dir", help=f"작업 문서 폴더(기본: 설정 또는 {DEFAULT_WORK_DIR})")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("setup", help="스크립트·템플릿·기본 설정을 프로젝트로 복사")
    p.add_argument("root", nargs="?", default=".")
    p.add_argument("--work-dir", dest="work_dir", default=DEFAULT_WORK_DIR)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=runtime.cmd_setup, needs_project=False)

    # config·list·report·queue show/next는 slug가 필요 없지만, 작업 명령 도구가 `<cmd> <slug>` 순서로
    # 넘기므로(`just feature-status _ list`) 자리 표시용 slug를 받아 무시한다.
    p = sub.add_parser("config", help="현재 설정 출력")
    p.add_argument("slug", nargs="?", help="무시됨(자리 표시)")
    p.set_defaults(func=cmd_config, needs_project=True)

    p = sub.add_parser("list", help="모든 기능의 진행 상태를 한 줄씩 출력")
    p.add_argument("slug", nargs="?", help="무시됨(자리 표시)")
    p.set_defaults(func=cmd_list, needs_project=True)

    p = sub.add_parser("report", help="회고용 요약 표(기본: done 기능만)")
    p.add_argument("slug", nargs="?", help="무시됨(자리 표시)")
    p.add_argument("--all", action="store_true")
    p.add_argument("--features", help="쉼표 구분 기능 ID. 지정하면 단계와 무관하게 그 기능만")
    p.set_defaults(func=cmd_report, needs_project=True)

    p = sub.add_parser("queue", help="기능 실행 순서·의존(queue.json). add/move/remove/depends는 slug, show/next는 `_`")
    p.add_argument("slug", help="기능 ID (show·next는 아무 값)")
    p.add_argument("action", choices=("add", "move", "remove", "depends", "show", "next"))
    p.add_argument("--depends-on", dest="depends_on", help="add: 선행 기능 ID(쉼표 구분)")
    p.add_argument("--set", dest="set", help="depends: 선행 기능 ID 목록으로 교체(빈 문자열이면 없음)")
    p.add_argument("--after", help="add/move: 이 기능 바로 뒤에")
    p.add_argument("--first", action="store_true", help="add/move: 맨 앞에")
    p.add_argument("--last", action="store_true", help="move: 맨 뒤에")
    p.add_argument("--prefix", help="next: 기능 ID 접두어(예: M2)")
    p.add_argument("--ids", help="next: 쉼표 구분 기능 ID로 범위 제한")
    p.set_defaults(func=cmd_queue, needs_project=True)

    p = sub.add_parser("init", help="status.json 생성")
    p.add_argument("slug")
    p.set_defaults(func=runtime.cmd_init, needs_project=True)

    p = sub.add_parser("show", help="진행 상태 출력")
    p.add_argument("slug")
    p.set_defaults(func=cmd_show, needs_project=True)

    p = sub.add_parser("phase", help="기능 단계 변경")
    p.add_argument("slug")
    p.add_argument("phase", choices=PHASES)
    p.add_argument("--note")
    p.set_defaults(func=runtime.cmd_phase, needs_project=True)

    p = sub.add_parser("step", help="작업 순서 항목 상태 변경")
    p.add_argument("slug")
    p.add_argument("id")
    p.add_argument("status", choices=STEP_STATUSES)
    p.add_argument("--note")
    p.set_defaults(func=runtime.cmd_step, needs_project=True)

    p = sub.add_parser("proof", help="증명 항목 상태 변경(키는 설정의 proof)")
    p.add_argument("slug")
    p.add_argument("key")
    p.add_argument("status", choices=PROOF_STATUSES)
    p.add_argument("--note")
    p.set_defaults(func=runtime.cmd_proof, needs_project=True)

    p = sub.add_parser("sync-plan", help="plan.md의 작업 순서(모델 태그 포함)를 steps로 가져오기")
    p.add_argument("slug")
    p.set_defaults(func=runtime.cmd_sync, needs_project=True)
    runtime.register(parser, sub, globals())
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not args.needs_project:
        args.func(args)
        return
    root = Path(args.root).resolve() if args.root else find_root(Path.cwd().resolve())
    args.func(Project(root, args.work_dir), args)


sys.dont_write_bytecode = True
import sdlc_runtime as runtime
runtime.bind(globals())

if __name__ == "__main__":
    try:
        main()
    except (ValueError, FileNotFoundError, json.JSONDecodeError) as exc:
        sys.exit(str(exc))
