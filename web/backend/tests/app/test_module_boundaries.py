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
class NameOwnership:
    """한 파일 안에서 이름마다 소유 모듈이 갈리는 경우의 매핑.

    `default`가 ``None``이면 매핑에 없는 이름은 실패한다(`app/models.py`처럼
    모든 이름의 소유가 정해져 있어야 하는 파일). `default`가 있으면 열거되지
    않은 이름은 파일 본체의 모듈로 본다(§5.2가 옮길 이름만 열거한 파일).
    """

    names: Mapping[str, str]
    default: str | None = None

    def resolve(self, name: str) -> str | None:
        if name in self.names:
            return self.names[name]
        return self.default


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
    # 이름 단위로 소유가 갈리는 파일: {"app/models.py": NameOwnership(...)}
    name_modules: Mapping[str, NameOwnership] = field(default_factory=dict)
    test_folder_modules: Mapping[str, str] = field(default_factory=dict)
    allowed_imports: Mapping[str, frozenset[str]] = field(default_factory=dict)
    # 방향은 금지지만 지정된 이름만 허용하는 seam: {(source, target): {name, ...}}
    seam_imports: Mapping[tuple[str, str], frozenset[str]] = field(default_factory=dict)
    # 방향은 허용이나 공개 표면 파일로만 받아야 하는 조합: {(source, target): 공개 표면 경로들}
    public_name_imports: Mapping[tuple[str, str], tuple[str, ...]] = field(default_factory=dict)
    # 그 규칙을 적용할 대상 경로 범위: {(source, target): 경로 prefix 또는 None}
    public_name_scopes: Mapping[tuple[str, str], str | None] = field(default_factory=dict)
    # §3의 예외: 각 모듈의 `models` 하위 모듈을 직접 들여도 되는 조립 파일들
    models_submodule_importers: tuple[str, ...] = ()
    # 검사 1의 대상 범위에서 빼는 폴더 (§8-1이 열거한 대상이 아닌 곳).
    # 자세한 근거는 `boundary_map.CHECK_ONE_EXEMPT_FOLDERS`의 주석에 있다.
    check_one_exempt_folders: tuple[str, ...] = ()
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

    def exempt_from_check_one(self, rel_path: str) -> bool:
        """§8-1이 검사 1의 대상으로 열거하지 않은 경로인가.

        §8-1의 대상은 `app/` 아래 모든 `.py`(조립 계층 포함)와
        `tests/<module>/` 아래 모든 `.py`다. `tests/app/`은 모듈 폴더가 아니라
        §5.4가 정한 "앱 조립·migration·runtime 계약·두 모듈 이상이 합쳐지는
        통합 검사"의 자리이므로 그 열거에 들어 있지 않다.
        """

        return any(
            rel_path == folder or rel_path.startswith(folder + "/")
            for folder in self.check_one_exempt_folders
        )

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
        name_modules=_repository_name_modules(root),
        test_folder_modules=bmap.TEST_FOLDER_MODULES,
        allowed_imports=bmap.ALLOWED_IMPORTS,
        seam_imports=bmap.SEAM_IMPORTS,
        public_name_imports=bmap.PUBLIC_NAME_IMPORTS,
        public_name_scopes=bmap.PUBLIC_NAME_SCOPES,
        models_submodule_importers=bmap.MODELS_SUBMODULE_IMPORTERS,
        check_one_exempt_folders=bmap.CHECK_ONE_EXEMPT_FOLDERS,
    )


def _repository_name_modules(root: Path) -> dict[str, NameOwnership]:
    """이름 단위 소유가 필요한 파일들의 매핑.

    §5.2가 다른 모듈로 옮길 이름만 열거한 파일은 그 이름에만 따로 소유를 준다
    (default = 파일 본체의 모듈). T6이 `app/models.py`를, T7 3단계가
    `app/schemas/__init__.py`와 마지막 split 항목을 없앴으므로 실제 저장소에서는
    비어 있고, 아래 합성 트리 테스트가 이 갈래를 계속 검사한다.
    """

    mapping: dict[str, NameOwnership] = {}
    for rel, (names, default) in bmap.SPLIT_FILE_NAME_MODULES.items():
        mapping[rel] = NameOwnership(names, default)
    return mapping


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
    """선언 파일의 모델 클래스 이름 → 소유 모듈 (§5.1 테이블 소유표).

    실제 저장소에서는 네 모듈의 `models.py`를 폴더 규칙이 판정하므로 더 쓰지
    않는다. 아래 합성 트리 테스트가 검사기 자신을 확인할 때 쓴다.
    """

    mapping: dict[str, str] = {}
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
        ownership = layout.name_modules.get(rel)
        for node in parse(path).body:
            if not isinstance(node, ast.ClassDef):
                continue
            table = _tablename(node)
            if table is None:
                continue
            if ownership is not None and node.name in ownership.names:
                owners[node.name] = ownership.names[node.name]
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


def _is_models_submodule_exception(rel: str, target_rel: str, layout: Layout) -> bool:
    """§3이 허용한 "조립 파일 → 모듈 `models`" import인가."""

    if not target_rel.endswith("/models.py"):
        return False
    return any(
        rel == allowed or rel.startswith(allowed)
        for allowed in layout.models_submodule_importers
    )


def _breaks_public_surface(layout: Layout, source: str, owner: str, target_rel: str) -> bool:
    """공개 이름 규칙이 켜진 조합에서 모듈 내부 경로를 직접 들었는가."""

    surface = layout.public_name_imports.get((source, owner))
    if surface is None:
        return False
    scope = layout.public_name_scopes.get((source, owner))
    if scope is not None and not target_rel.startswith(scope):
        # 아직 그 모듈 폴더 밖에 있는 소유 파일. 규칙 범위 밖이다.
        return False
    return target_rel not in surface


def resolved_imports(layout: Layout):
    """`(파일, 출발 모듈, 도착 모듈, 도착 경로, import 대상)`을 차례로 낸다."""

    for path in layout.source_files():
        rel = layout.rel(path)
        if layout.exempt_from_check_one(rel):
            # §8-1이 검사 1의 대상으로 열거하지 않은 경로(`tests/app/`).
            # `app/**`와 `tests/<module>/`는 그대로 검사한다.
            continue
        source = layout.module_for(rel)
        if source is None:  # 섞인 파일은 출발지로 검사하지 않는다.
            continue
        for target in imports_of(path, layout):
            target_rel = layout.path_for_dotted(target.dotted)
            if target_rel is None or target_rel in layout.excluded_files:
                continue
            ownership = layout.name_modules.get(target_rel)
            if ownership is not None:
                if target.name is None:
                    # 모듈 전체 import는 이름을 특정할 수 없다. 파일 본체의
                    # 모듈이 정해져 있으면 그것으로 보고, 아니면 넘어간다.
                    owner = ownership.default
                else:
                    owner = ownership.resolve(target.name)
                    if owner is None:
                        raise AssertionError(
                            f"{target_rel}의 '{target.name}' 소유 모듈이 매핑표에 없다 "
                            f"({rel}:{target.lineno})"
                        )
            else:
                owner = layout.module_for(target_rel)
            if owner is None:
                continue
            yield rel, source, owner, target_rel, target


def check_cross_module_imports(layout: Layout) -> set[Violation]:
    violations: set[Violation] = set()
    for rel, source, owner, target_rel, target in resolved_imports(layout):
        allowed = set(layout.allowed_imports.get(source, frozenset())) | {source}
        if _is_models_submodule_exception(rel, target_rel, layout):
            # §3의 예외: alembic/env.py와 revision 파일은 각 모듈의 `models`를
            # 직접 들여 선언 테이블을 모두 등록한다.
            continue
        if _breaks_public_surface(layout, source, owner, target_rel):
            # 방향은 허용이지만 모듈 내부 경로를 직접 들었다 (§3·§4).
            violations.add(Violation(rel, CROSS_MODULE_IMPORT, target.label))
            continue
        if owner in allowed:
            continue
        seam = layout.seam_imports.get((source, owner))
        if seam is not None and target.name is not None and target.name in seam:
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


def test_excluded_files_still_exist() -> None:
    """실재하지 않는 경로가 EXCLUDED_FILES에 남아 있으면 실패한다.

    허용 목록의 stale 항목을 막는 것과 같은 취지다. 사라진 파일의 제외가
    남아 있으면 그 제외는 아무 일도 하지 않으면서 다음 사람을 헷갈리게 한다.
    """

    stale = sorted(rel for rel in bmap.EXCLUDED_FILES if not (BACKEND_ROOT / rel).is_file())
    assert not stale, (
        "EXCLUDED_FILES에 실재하지 않는 경로가 있다. 지워야 한다:\n"
        + "\n".join(f"  {rel}" for rel in stale)
    )


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
            "app/models.py": NameOwnership(
                {
                    "Notice": bmap.LIFECYCLE,
                    "Judgment": bmap.SCREENING,
                    "DeepReview": bmap.DEEP_REVIEW,
                }
            ),
            "app/services.py": NameOwnership(
                {"shared_helper": bmap.CORE}, bmap.SCREENING
            ),
        },
        allowed_imports=bmap.ALLOWED_IMPORTS,
        seam_imports=bmap.SEAM_IMPORTS,
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


def test_checker_flags_deep_review_reaching_into_screening(synthetic: Layout) -> None:
    """§4: deep_review는 screening 내부 ORM·service를 쓰지 못한다."""

    _write(
        synthetic.root,
        "app/deep_review/versions.py",
        "from ..models import Judgment\nfrom ..screening.store import JudgmentStore\n",
    )
    _write(synthetic.root, "app/screening/store.py", "JudgmentStore = None\n")
    found = as_tuples(check_cross_module_imports(synthetic))
    assert ("app/deep_review/versions.py", CROSS_MODULE_IMPORT, "app.models:Judgment") in found
    assert (
        "app/deep_review/versions.py",
        CROSS_MODULE_IMPORT,
        "app.screening.store:JudgmentStore",
    ) in found


def test_checker_allows_the_deep_review_to_screening_seam(synthetic: Layout) -> None:
    """§6.3의 읽기 전용 seam 함수 두 개만은 허용이다."""

    _write(
        synthetic.root,
        "app/deep_review/versions.py",
        "from ..screening import current_judgment, latest_corrected_grade\n",
    )
    assert check_cross_module_imports(synthetic) == set()


def _assembly_surface_layout(root: Path) -> Layout:
    """조립 계층이 모듈 공개 이름만 받아야 하는, 실제 저장소와 같은 모양의 트리.

    `tests/app`은 §8-1이 검사 1의 대상으로 열거하지 않았으므로 면제 목록에
    들어간다. `app/main.py`는 열거된 대상이라 그대로 검사한다.
    """

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
        test_folder_modules={"tests/app": bmap.ASSEMBLY, "tests/screening": bmap.SCREENING},
        allowed_imports=bmap.ALLOWED_IMPORTS,
        seam_imports=bmap.SEAM_IMPORTS,
        public_name_imports={("assembly", "screening"): ("app/screening/__init__.py",)},
        public_name_scopes={("assembly", "screening"): None},
        check_one_exempt_folders=("tests/app",),
    )


@pytest.fixture()
def assembly_surface(tmp_path: Path) -> Layout:
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/main.py", "")
    for module in ("core", "lifecycle", "screening", "deep_review"):
        _write(tmp_path, f"app/{module}/__init__.py", "")
    _write(tmp_path, "app/screening/models.py", "Judgment = None\n")
    _write(tmp_path, "tests/__init__.py", "")
    _write(tmp_path, "tests/app/__init__.py", "")
    _write(tmp_path, "tests/screening/__init__.py", "")
    return _assembly_surface_layout(tmp_path)


def test_check_one_skips_tests_app_but_not_the_assembly_layer(
    assembly_surface: Layout,
) -> None:
    """§8-1의 대상 범위: `app/`은 검사하고 `tests/app/`은 검사하지 않는다.

    두 파일이 **똑같은** 모듈 내부 import를 한다. 조립 계층 파일
    (`app/main.py`)은 여전히 위반으로 잡혀야 하고, §5.4가 통합 검사의 자리로
    정한 `tests/app/`의 파일은 잡히지 않아야 한다. 이 테스트가 실패하는
    방향은 둘 다 회귀다 — 위쪽이 빠지면 production 보장이 줄어든 것이고,
    아래쪽이 잡히면 §5.4의 배치가 다시 불가능해진다.
    """

    internal_import = "from app.screening.models import Judgment\n"
    _write(assembly_surface.root, "app/main.py", internal_import)
    _write(assembly_surface.root, "tests/app/test_integration.py", internal_import)

    found = as_tuples(check_cross_module_imports(assembly_surface))
    assert ("app/main.py", CROSS_MODULE_IMPORT, "app.screening.models:Judgment") in found
    assert not [entry for entry in found if entry[0].startswith("tests/app/")]


def test_check_one_still_guards_module_test_folders(assembly_surface: Layout) -> None:
    """면제는 `tests/app/`뿐이다. `tests/<module>/`은 §5.4대로 계속 검사한다."""

    _write(
        assembly_surface.root,
        "tests/screening/test_leak.py",
        "from app.deep_review import build_runtime\n",
    )
    _write(assembly_surface.root, "app/deep_review/__init__.py", "build_runtime = None\n")
    found = as_tuples(check_cross_module_imports(assembly_surface))
    assert (
        "tests/screening/test_leak.py",
        CROSS_MODULE_IMPORT,
        "app.deep_review:build_runtime",
    ) in found


def test_check_one_exempt_folders_are_only_test_folders() -> None:
    """면제 목록이 `app/`이나 `alembic/`으로 번지지 않는다.

    §8-1이 검사 1의 대상으로 못박은 production 경로는 어떤 이유로도 면제
    목록에 들어갈 수 없다.
    """

    assert bmap.CHECK_ONE_EXEMPT_FOLDERS == ("tests/app",)
    for folder in bmap.CHECK_ONE_EXEMPT_FOLDERS:
        assert folder.startswith("tests/")
        assert folder not in bmap.MODULE_FOLDERS
        assert (BACKEND_ROOT / folder).is_dir()


def test_checker_resolves_split_service_names_by_owner(synthetic: Layout) -> None:
    """§5.2가 다른 모듈로 옮기기로 열거한 이름은 그 모듈 것으로 본다."""

    _write(
        synthetic.root,
        "app/services.py",
        "shared_helper = None\nscreening_only = None\n",
    )
    _write(
        synthetic.root,
        "app/lifecycle/service.py",
        "from ..services import shared_helper, screening_only\n",
    )
    found = as_tuples(check_cross_module_imports(synthetic))
    # core로 옮기기로 열거된 이름은 위반이 아니다.
    assert ("app/lifecycle/service.py", CROSS_MODULE_IMPORT, "app.services:shared_helper") not in found
    # 열거되지 않은 이름은 파일 본체(screening)의 것으로 본다.
    assert ("app/lifecycle/service.py", CROSS_MODULE_IMPORT, "app.services:screening_only") in found


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
        name_modules={
            "app/models.py": NameOwnership(model_name_modules(tmp_path / "app" / "models.py"))
        },
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
