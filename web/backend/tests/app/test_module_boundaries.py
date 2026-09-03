"""명세 §8의 경계 강제 테스트.

네 검사는 순수 함수다. 실제 저장소를 훑는 `repository_layout()` 말고도 합성
트리(`Layout`)를 그대로 받을 수 있어야 검사기 자신을 테스트할 수 있고, 이
파일 아래쪽이 그렇게 한다 — 가짜 위반이 잡히는지, 허용 목록의 stale 항목이
실패를 내는지.

허용 목록은 `tests/app/boundary_allowlist.py`, 경로·이름 → 모듈 매핑표는
`tests/app/boundary_map.py`에 데이터로 있다. 이주 task는 그 두 파일만 줄인다.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Iterable, Mapping

import pytest

from . import boundary_allowlist as allowlist
from . import boundary_map as bmap

CROSS_MODULE_IMPORT = "cross_module_import"
ROUTER_ORM_ACCESS = "router_orm_access"
SCHEMA_IMPORTS_MODEL_OR_SERVICE = "schema_imports_model_or_service"
LIFECYCLE_RELATIONSHIP = "lifecycle_relationship"

#: 검사 2가 금지하는 호출·import. 값은 허용 목록에 적히는 대상 이름이다.
ROUTER_SELECT = "sqlalchemy.select"
ROUTER_EXECUTE = "Session.execute"
ROUTER_QUERY = ".query("


@dataclass(frozen=True, order=True)
class Violation:
    """`(파일, 위반 종류, 대상)`."""

    path: str
    kind: str
    target: str

    def as_tuple(self) -> tuple[str, str, str]:
        return (self.path, self.kind, self.target)


@dataclass(frozen=True)
class Layout:
    """검사 대상 트리와 그 경로 → 모듈 매핑."""

    root: Path
    package_roots: tuple[str, ...] = ("app", "alembic")
    file_modules: Mapping[str, str] = field(default_factory=dict)
    directory_modules: Mapping[str, str] = field(default_factory=dict)
    module_folders: Mapping[str, str] = field(default_factory=dict)
    folder_exceptions: Mapping[str, str] = field(default_factory=dict)
    mixed_files: frozenset[str] = frozenset()
    excluded_files: frozenset[str] = frozenset()
    # 섞인 파일의 이름 단위 소유: {"app/models.py": {"Judgment": "screening", ...}}
    name_modules: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    test_folder_modules: Mapping[str, str] = field(default_factory=dict)
    allowed_imports: Mapping[str, frozenset[str]] = field(default_factory=dict)
    default_module: str | None = bmap.ASSEMBLY

    # --- 경로 헬퍼 -------------------------------------------------------
    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    def source_files(self) -> list[Path]:
        found: list[Path] = []
        for base in self.package_roots:
            root = self.root / base
            if root.is_dir():
                found.extend(sorted(root.rglob("*.py")))
        for folder in sorted(self.test_folder_modules):
            root = self.root / folder
            if root.is_dir():
                found.extend(sorted(root.rglob("*.py")))
        return [p for p in found if self.rel(p) not in self.excluded_files]

    def module_for(self, rel_path: str) -> str | None:
        """경로가 속할 목표 모듈. 섞인 파일이면 ``None``."""

        if rel_path in self.mixed_files:
            return None
        if rel_path in self.folder_exceptions:
            return self.folder_exceptions[rel_path]
        # (a) 이미 존재하는 모듈 폴더를 먼저 본다.
        for folder, module in sorted(self.module_folders.items(), key=lambda kv: -len(kv[0])):
            if rel_path == folder or rel_path.startswith(folder + "/"):
                return module
        for folder, module in sorted(self.test_folder_modules.items(), key=lambda kv: -len(kv[0])):
            if rel_path == folder or rel_path.startswith(folder + "/"):
                return module
        # (b) 없으면 명시적 매핑표를 본다.
        if rel_path in self.file_modules:
            return self.file_modules[rel_path]
        for folder, module in sorted(self.directory_modules.items(), key=lambda kv: -len(kv[0])):
            if rel_path.startswith(folder + "/"):
                return module
        return self.default_module

    def dotted_for(self, rel_path: str) -> str:
        parts = rel_path[: -len(".py")].split("/")
        if parts[-1] == "__init__":
            parts = parts[:-1]
        return ".".join(parts)

    def path_for_dotted(self, dotted: str) -> str | None:
        base = dotted.replace(".", "/")
        for candidate in (f"{base}.py", f"{base}/__init__.py"):
            if (self.root / candidate).is_file():
                return candidate
        return None


def repository_layout(root: Path) -> Layout:
    return Layout(
        root=root,
        file_modules=bmap.FILE_MODULES,
        directory_modules=bmap.DIRECTORY_MODULES,
        module_folders=bmap.MODULE_FOLDERS,
        folder_exceptions=bmap.FOLDER_EXCEPTIONS,
        mixed_files=bmap.MIXED_FILES,
        excluded_files=bmap.EXCLUDED_FILES,
        name_modules={
            "app/models.py": model_name_modules(root / "app" / "models.py"),
            "app/schemas/__init__.py": bmap.SCHEMAS_NAME_MODULE,
        },
        test_folder_modules=bmap.TEST_FOLDER_MODULES,
        allowed_imports=bmap.ALLOWED_IMPORTS,
    )


def parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


# --- 모델 클래스 -----------------------------------------------------------


def _tablename(node: ast.ClassDef) -> str | None:
    for stmt in node.body:
        targets: list[ast.expr] = []
        if isinstance(stmt, ast.Assign):
            targets = list(stmt.targets)
            value = stmt.value
        elif isinstance(stmt, ast.AnnAssign):
            targets = [stmt.target]
            value = stmt.value
        else:
            continue
        if any(isinstance(t, ast.Name) and t.id == "__tablename__" for t in targets):
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


def model_name_modules(models_path: Path) -> dict[str, str]:
    """`app/models.py`의 이름 → 소유 모듈 (§5.1 테이블 소유 + 비테이블 이름)."""

    mapping = dict(bmap.MODELS_EXTRA_NAMES)
    if not models_path.is_file():
        return mapping
    for node in parse(models_path).body:
        if not isinstance(node, ast.ClassDef):
            continue
        table = _tablename(node)
        if table is None:
            continue
        owner = bmap.TABLE_OWNER.get(table)
        if owner is None:
            raise AssertionError(
                f"{models_path.name}: 테이블 '{table}'({node.name})의 소유 모듈이 §5.1에 없다"
            )
        mapping[node.name] = owner
    return mapping


def collect_model_classes(layout: Layout) -> dict[str, str]:
    """선언적 모델 클래스 이름 → 소유 모듈 (모든 대상 파일에서)."""

    owners: dict[str, str] = {}
    for path in layout.source_files():
        rel = layout.rel(path)
        names = layout.name_modules.get(rel)
        for node in parse(path).body:
            if not isinstance(node, ast.ClassDef):
                continue
            table = _tablename(node)
            if table is None:
                continue
            if names is not None and node.name in names:
                owners[node.name] = names[node.name]
            else:
                owner = bmap.TABLE_OWNER.get(table) or layout.module_for(rel)
                if owner is not None:
                    owners[node.name] = owner
    return owners


# --- import 해석 -----------------------------------------------------------


@dataclass(frozen=True)
class ImportTarget:
    dotted: str
    name: str | None
    lineno: int

    @property
    def label(self) -> str:
        return f"{self.dotted}:{self.name}" if self.name else self.dotted


def _resolve_relative(rel_path: str, level: int, module: str | None, layout: Layout) -> str | None:
    parts = layout.dotted_for(rel_path).split(".")
    if not rel_path.endswith("__init__.py"):
        parts = parts[:-1]
    if level - 1 > len(parts):
        return None
    base = parts[: len(parts) - (level - 1)] if level > 1 else parts
    dotted = ".".join([*base, module] if module else base)
    return dotted or None


def imports_of(path: Path, layout: Layout) -> list[ImportTarget]:
    """파일이 참조하는 저장소 내부 모듈 목록."""

    rel = layout.rel(path)
    found: list[ImportTarget] = []
    for node in ast.walk(parse(path)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if layout.path_for_dotted(alias.name):
                    found.append(ImportTarget(alias.name, None, node.lineno))
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            base = _resolve_relative(rel, node.level, node.module, layout)
        else:
            base = node.module
        if not base or not layout.path_for_dotted(base):
            continue
        for alias in node.names:
            submodule = f"{base}.{alias.name}"
            if layout.path_for_dotted(submodule):
                found.append(ImportTarget(submodule, None, node.lineno))
            else:
                found.append(ImportTarget(base, alias.name, node.lineno))
    return found


# --- 검사 1: 모듈 간 import 방향 -------------------------------------------


def check_cross_module_imports(layout: Layout) -> set[Violation]:
    violations: set[Violation] = set()
    for path in layout.source_files():
        rel = layout.rel(path)
        source = layout.module_for(rel)
        if source is None:  # 섞인 파일은 출발지로 검사하지 않는다.
            continue
        allowed = set(layout.allowed_imports.get(source, frozenset())) | {source}
        for target in imports_of(path, layout):
            target_rel = layout.path_for_dotted(target.dotted)
            if target_rel is None or target_rel in layout.excluded_files:
                continue
            names = layout.name_modules.get(target_rel)
            if names is not None:
                if target.name is None:
                    continue  # 모듈 전체 import는 이름을 특정할 수 없다.
                owner = names.get(target.name)
                if owner is None:
                    raise AssertionError(
                        f"{target_rel}의 '{target.name}' 소유 모듈이 매핑표에 없다 ({rel}:{target.lineno})"
                    )
            else:
                owner = layout.module_for(target_rel)
            if owner is None or owner in allowed:
                continue
            violations.add(Violation(rel, CROSS_MODULE_IMPORT, target.label))
    return violations


# --- 검사 2: router 안의 ORM 접근 -------------------------------------------


def _is_router(rel_path: str) -> bool:
    return "/routers/" in rel_path and not rel_path.endswith("/__init__.py")


def check_router_orm_access(layout: Layout) -> set[Violation]:
    violations: set[Violation] = set()
    for path in layout.source_files():
        rel = layout.rel(path)
        if not _is_router(rel):
            continue
        tree = parse(path)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "sqlalchemy":
                if any(alias.name == "select" for alias in node.names):
                    violations.add(Violation(rel, ROUTER_ORM_ACCESS, ROUTER_SELECT))
            elif isinstance(node, ast.Attribute) and node.attr == "select":
                base = node.value
                if isinstance(base, ast.Name) and base.id == "sqlalchemy":
                    violations.add(Violation(rel, ROUTER_ORM_ACCESS, ROUTER_SELECT))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "execute":
                    violations.add(Violation(rel, ROUTER_ORM_ACCESS, ROUTER_EXECUTE))
                elif node.func.attr == "query":
                    violations.add(Violation(rel, ROUTER_ORM_ACCESS, ROUTER_QUERY))
    return violations


# --- 검사 3: schemas → models·services ---------------------------------------


def _is_schema(rel_path: str) -> bool:
    return "/schemas/" in rel_path or rel_path.endswith("/schemas.py")


def check_schema_imports(layout: Layout) -> set[Violation]:
    violations: set[Violation] = set()
    for path in layout.source_files():
        rel = layout.rel(path)
        if not _is_schema(rel):
            continue
        for target in imports_of(path, layout):
            parts = target.dotted.split(".")
            if "models" in parts or "services" in parts:
                violations.add(Violation(rel, SCHEMA_IMPORTS_MODEL_OR_SERVICE, target.dotted))
    return violations


# --- 검사 4: lifecycle 모델의 바깥 방향 relationship --------------------------


def _relationship_targets(node: ast.AnnAssign | ast.Assign) -> tuple[str, ...]:
    raw: list[str] = []
    annotation = node.annotation if isinstance(node, ast.AnnAssign) else None
    if annotation is not None:
        for inner in ast.walk(annotation):
            if isinstance(inner, ast.Constant) and isinstance(inner.value, str):
                raw.append(inner.value)
    if not raw and isinstance(node.value, ast.Call) and node.value.args:
        first = node.value.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            raw.append(first.value)
    names: list[str] = []
    for text in raw:
        for piece in text.replace("[", " ").replace("]", " ").split("|"):
            candidate = piece.strip()
            if candidate and candidate != "None" and candidate.isidentifier():
                names.append(candidate)
    return tuple(dict.fromkeys(names))


def _is_relationship(node: ast.AnnAssign | ast.Assign) -> bool:
    call = node.value
    if not isinstance(call, ast.Call):
        return False
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "relationship"
    return isinstance(func, ast.Attribute) and func.attr == "relationship"


def check_lifecycle_relationships(layout: Layout) -> set[Violation]:
    owners = collect_model_classes(layout)
    violations: set[Violation] = set()
    for path in layout.source_files():
        rel = layout.rel(path)
        for node in parse(path).body:
            if not isinstance(node, ast.ClassDef):
                continue
            if owners.get(node.name) != bmap.LIFECYCLE:
                continue
            for stmt in node.body:
                if not isinstance(stmt, (ast.AnnAssign, ast.Assign)):
                    continue
                if not _is_relationship(stmt):
                    continue
                if isinstance(stmt, ast.AnnAssign):
                    if not isinstance(stmt.target, ast.Name):
                        continue
                    attribute = stmt.target.id
                else:
                    targets = [t for t in stmt.targets if isinstance(t, ast.Name)]
                    if not targets:
                        continue
                    attribute = targets[0].id
                for referenced in _relationship_targets(stmt):
                    owner = owners.get(referenced)
                    if owner is None or owner == bmap.LIFECYCLE:
                        continue
                    violations.add(
                        Violation(rel, LIFECYCLE_RELATIONSHIP, f"{node.name}.{attribute}")
                    )
    return violations


CHECKS = {
    CROSS_MODULE_IMPORT: check_cross_module_imports,
    ROUTER_ORM_ACCESS: check_router_orm_access,
    SCHEMA_IMPORTS_MODEL_OR_SERVICE: check_schema_imports,
    LIFECYCLE_RELATIONSHIP: check_lifecycle_relationships,
}


def as_tuples(violations: Iterable[Violation]) -> list[tuple[str, str, str]]:
    return sorted(v.as_tuple() for v in violations)


def unmapped_source_files(layout: Layout) -> list[str]:
    """폴더 규칙·매핑표·섞인 파일 어디에도 없는 파일."""

    known = set(layout.file_modules) | set(layout.mixed_files) | set(layout.folder_exceptions)
    folders = tuple(layout.module_folders) + tuple(layout.directory_modules) + tuple(layout.test_folder_modules)
    missing: list[str] = []
    for path in layout.source_files():
        rel = layout.rel(path)
        if rel in known:
            continue
        if any(rel.startswith(folder + "/") for folder in folders):
            continue
        missing.append(rel)
    return missing


# ---------------------------------------------------------------------------
# 실제 저장소에 대한 §8의 네 검사
# ---------------------------------------------------------------------------

BACKEND_ROOT = Path(__file__).resolve().parents[2]

ALLOWLISTS: dict[str, frozenset[tuple[str, str, str]]] = {
    CROSS_MODULE_IMPORT: allowlist.CROSS_MODULE_IMPORT_ALLOWLIST,
    ROUTER_ORM_ACCESS: allowlist.ROUTER_ORM_ALLOWLIST,
    SCHEMA_IMPORTS_MODEL_OR_SERVICE: allowlist.SCHEMA_IMPORT_ALLOWLIST,
    LIFECYCLE_RELATIONSHIP: allowlist.LIFECYCLE_RELATIONSHIP_ALLOWLIST,
}


@pytest.fixture(scope="module")
def layout() -> Layout:
    return repository_layout(BACKEND_ROOT)


def _assert_matches_allowlist(kind: str, found: set[Violation]) -> None:
    allowed = ALLOWLISTS[kind]
    actual = set(as_tuples(found))
    new = sorted(actual - allowed)
    stale = sorted(allowed - actual)
    problems: list[str] = []
    if new:
        problems.append(
            "허용 목록에 없는 새 위반:\n" + "\n".join(f"  + {entry}" for entry in new)
        )
    if stale:
        problems.append(
            "더 이상 위반이 아닌데 허용 목록에 남아 있는 항목 (지워야 한다):\n"
            + "\n".join(f"  - {entry}" for entry in stale)
        )
    assert not problems, f"[{kind}]\n" + "\n".join(problems)


def test_every_source_file_is_assigned_to_a_module(layout: Layout) -> None:
    missing = unmapped_source_files(layout)
    assert not missing, (
        "목표 모듈이 정해지지 않은 파일이 있다. tests/app/boundary_map.py의 "
        f"FILE_MODULES 또는 MIXED_FILES에 추가한다:\n" + "\n".join(f"  {rel}" for rel in missing)
    )


def test_cross_module_imports_follow_the_dependency_table(layout: Layout) -> None:
    _assert_matches_allowlist(CROSS_MODULE_IMPORT, check_cross_module_imports(layout))


def test_routers_do_not_touch_the_orm_directly(layout: Layout) -> None:
    _assert_matches_allowlist(ROUTER_ORM_ACCESS, check_router_orm_access(layout))


def test_schemas_do_not_import_models_or_services(layout: Layout) -> None:
    _assert_matches_allowlist(SCHEMA_IMPORTS_MODEL_OR_SERVICE, check_schema_imports(layout))


def test_lifecycle_models_have_no_outbound_relationships(layout: Layout) -> None:
    _assert_matches_allowlist(LIFECYCLE_RELATIONSHIP, check_lifecycle_relationships(layout))


def test_declared_tables_match_the_ownership_table(layout: Layout) -> None:
    """§5.1의 테이블 소유표가 실제 선언과 정확히 맞는다."""

    declared: dict[str, str] = {}
    for path in layout.source_files():
        for node in parse(path).body:
            if isinstance(node, ast.ClassDef):
                table = _tablename(node)
                if table is not None:
                    declared[table] = node.name
    assert declared, "선언적 모델 클래스를 하나도 찾지 못했다"
    missing = sorted(set(declared) - set(bmap.TABLE_OWNER))
    extra = sorted(set(bmap.TABLE_OWNER) - set(declared))
    assert not missing, f"§5.1 소유표에 없는 테이블: {missing}"
    assert not extra, f"§5.1 소유표에만 있고 선언되지 않은 테이블: {extra}"


def test_allowlists_have_no_duplicate_or_foreign_kinds() -> None:
    for kind, entries in ALLOWLISTS.items():
        assert all(entry[1] == kind for entry in entries), f"{kind} 목록에 다른 종류가 섞여 있다"


def test_allowlists_only_shrink() -> None:
    """새 위반을 허용 목록에 얹어 정당화하는 경로를 막는다."""

    for kind, entries in ALLOWLISTS.items():
        baseline = allowlist.BASELINE_SIZES[kind]
        assert len(entries) <= baseline, (
            f"[{kind}] 허용 목록이 기준선({baseline})보다 커졌다: {len(entries)}. "
            "허용 목록은 줄어드는 방향만 허용한다."
        )


def test_every_schema_name_has_an_owning_module() -> None:
    """`app/schemas/__init__.py`에 새 이름이 생기면 소유 모듈을 정하게 만든다."""

    schemas_path = BACKEND_ROOT / "app" / "schemas" / "__init__.py"
    if not schemas_path.is_file():  # T7 이후에는 파일이 사라진다.
        return
    declared: list[str] = []
    for node in parse(schemas_path).body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            declared.append(node.name)
        elif isinstance(node, ast.Assign):
            declared.extend(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            declared.append(node.target.id)
    missing = sorted(set(declared) - set(bmap.SCHEMAS_NAME_MODULE))
    assert not missing, (
        "boundary_map.SCHEMAS_NAME_MODULE에 소유 모듈이 없는 이름:\n"
        + "\n".join(f"  {name}" for name in missing)
    )


# ---------------------------------------------------------------------------
# 검사기 자신에 대한 테스트 (합성 트리)
# ---------------------------------------------------------------------------


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(source), encoding="utf-8")


def _synthetic_layout(root: Path) -> Layout:
    """네 모듈이 폴더로 이미 나뉜 작은 트리."""

    return Layout(
        root=root,
        package_roots=("app",),
        module_folders={
            "app/core": bmap.CORE,
            "app/lifecycle": bmap.LIFECYCLE,
            "app/screening": bmap.SCREENING,
            "app/deep_review": bmap.DEEP_REVIEW,
        },
        file_modules={"app/main.py": bmap.ASSEMBLY},
        mixed_files=frozenset({"app/models.py"}),
        name_modules={
            "app/models.py": {
                "Notice": bmap.LIFECYCLE,
                "Judgment": bmap.SCREENING,
                "DeepReview": bmap.DEEP_REVIEW,
            }
        },
        allowed_imports=bmap.ALLOWED_IMPORTS,
    )


@pytest.fixture()
def synthetic(tmp_path: Path) -> Layout:
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/main.py", "")
    _write(tmp_path, "app/models.py", "")
    for module in ("core", "lifecycle", "screening", "deep_review"):
        _write(tmp_path, f"app/{module}/__init__.py", "")
    return _synthetic_layout(tmp_path)


def test_checker_flags_a_backwards_import(synthetic: Layout) -> None:
    _write(synthetic.root, "app/lifecycle/service.py", "from ..screening.policy import activate\n")
    _write(synthetic.root, "app/screening/policy.py", "activate = None\n")
    found = as_tuples(check_cross_module_imports(synthetic))
    assert (
        "app/lifecycle/service.py",
        CROSS_MODULE_IMPORT,
        "app.screening.policy:activate",
    ) in found


def test_checker_allows_the_permitted_direction(synthetic: Layout) -> None:
    _write(synthetic.root, "app/screening/policy.py", "from ..lifecycle.service import ingest_run\n")
    _write(synthetic.root, "app/lifecycle/service.py", "ingest_run = None\n")
    assert check_cross_module_imports(synthetic) == set()


def test_checker_resolves_mixed_model_imports_by_name(synthetic: Layout) -> None:
    _write(synthetic.root, "app/lifecycle/service.py", "from ..models import Judgment, Notice\n")
    found = as_tuples(check_cross_module_imports(synthetic))
    assert ("app/lifecycle/service.py", CROSS_MODULE_IMPORT, "app.models:Judgment") in found
    assert ("app/lifecycle/service.py", CROSS_MODULE_IMPORT, "app.models:Notice") not in found


def test_checker_ignores_absolute_imports_of_external_packages(synthetic: Layout) -> None:
    _write(synthetic.root, "app/core/util.py", "import json\nfrom sqlalchemy import select\n")
    assert check_cross_module_imports(synthetic) == set()


def test_checker_flags_router_orm_access(synthetic: Layout) -> None:
    _write(
        synthetic.root,
        "app/screening/routers/notices.py",
        """
        from sqlalchemy import select

        def handler(session):
            session.execute(select(1))
            session.query(None)
        """,
    )
    found = as_tuples(check_router_orm_access(synthetic))
    rel = "app/screening/routers/notices.py"
    assert (rel, ROUTER_ORM_ACCESS, ROUTER_SELECT) in found
    assert (rel, ROUTER_ORM_ACCESS, ROUTER_EXECUTE) in found
    assert (rel, ROUTER_ORM_ACCESS, ROUTER_QUERY) in found


def test_checker_leaves_clean_routers_alone(synthetic: Layout) -> None:
    _write(
        synthetic.root,
        "app/screening/routers/notices.py",
        """
        from ..services import list_notices

        def handler(session):
            return list_notices(session)
        """,
    )
    _write(synthetic.root, "app/screening/services.py", "list_notices = None\n")
    assert check_router_orm_access(synthetic) == set()


def test_checker_flags_schema_importing_models_and_services(synthetic: Layout) -> None:
    _write(
        synthetic.root,
        "app/screening/schemas/__init__.py",
        "from ...models import Judgment\nfrom ..services import list_notices\n",
    )
    _write(synthetic.root, "app/screening/services.py", "list_notices = None\n")
    found = as_tuples(check_schema_imports(synthetic))
    rel = "app/screening/schemas/__init__.py"
    assert (rel, SCHEMA_IMPORTS_MODEL_OR_SERVICE, "app.models") in found
    assert (rel, SCHEMA_IMPORTS_MODEL_OR_SERVICE, "app.screening.services") in found


def test_checker_flags_lifecycle_relationship_to_another_module(tmp_path: Path) -> None:
    _write(tmp_path, "app/__init__.py", "")
    _write(
        tmp_path,
        "app/models.py",
        """
        class Notice(Base):
            __tablename__ = "notice"

            judgment: Mapped["Judgment | None"] = relationship(back_populates="notice")
            observations: Mapped[list["NoticeObservation"]] = relationship()

        class NoticeObservation(Base):
            __tablename__ = "notice_observation"

        class Judgment(Base):
            __tablename__ = "judgment"

            notice: Mapped["Notice"] = relationship(back_populates="judgment")
        """,
    )
    layout = Layout(
        root=tmp_path,
        package_roots=("app",),
        mixed_files=frozenset({"app/models.py"}),
        name_modules={"app/models.py": model_name_modules(tmp_path / "app" / "models.py")},
        allowed_imports=bmap.ALLOWED_IMPORTS,
    )
    found = as_tuples(check_lifecycle_relationships(layout))
    assert ("app/models.py", LIFECYCLE_RELATIONSHIP, "Notice.judgment") in found
    # 허용 방향: screening 모델이 lifecycle 모델을 가리키는 것은 위반이 아니다.
    assert ("app/models.py", LIFECYCLE_RELATIONSHIP, "Judgment.notice") not in found
    # 같은 모듈 안의 relationship도 위반이 아니다.
    assert ("app/models.py", LIFECYCLE_RELATIONSHIP, "Notice.observations") not in found


def test_stale_allowlist_entry_fails() -> None:
    stale = ("app/gone.py", CROSS_MODULE_IMPORT, "app.models:Judgment")
    with pytest.raises(AssertionError) as excinfo:
        _compare(frozenset({stale}), set())
    assert "더 이상 위반이 아닌데" in str(excinfo.value)


def test_new_violation_not_in_allowlist_fails() -> None:
    found = {Violation("app/new.py", CROSS_MODULE_IMPORT, "app.models:Judgment")}
    with pytest.raises(AssertionError) as excinfo:
        _compare(frozenset(), found)
    assert "허용 목록에 없는 새 위반" in str(excinfo.value)


def test_matching_allowlist_passes() -> None:
    entry = ("app/kept.py", CROSS_MODULE_IMPORT, "app.models:Judgment")
    _compare(frozenset({entry}), {Violation(*entry)})


def _compare(allowed: frozenset[tuple[str, str, str]], found: set[Violation]) -> None:
    """`_assert_matches_allowlist`와 같은 비교를 임의의 목록으로 수행한다."""

    kind = CROSS_MODULE_IMPORT
    original = ALLOWLISTS[kind]
    ALLOWLISTS[kind] = allowed
    try:
        _assert_matches_allowlist(kind, found)
    finally:
        ALLOWLISTS[kind] = original
