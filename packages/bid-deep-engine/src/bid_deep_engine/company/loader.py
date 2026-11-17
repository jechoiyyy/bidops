"""회사 프로필 로더와 검증(load_profile, validate). 네트워크를 쓰지 않고 파일만 읽는다.

- 프로필 YAML과 `portfolio_file`(프로필과 같은 폴더 기준)을 읽고, PyYAML이 만든 `date`를
  `isoformat()` 문자열로 바꾼 뒤 실적을 `portfolio`로 넣어 `CompanyProfile` 하나로 검증한다.
- `validate`는 예외 없이 `ValidationReport`를 돌려준다. 오류·경고 한 줄 = `"<경로>: <내용>"`.
- 오류 경로(X37): 점 경로, 목록 항목은 유효한 식별 키면 `[키 값]`, 아니면 `[#인덱스]`,
  union 분기 오류는 경로당 한 줄(`<첫 분기 메시지>; 허용: <분기 목록>`).
- 실적 ID 형식·중복은 규칙 3 한 곳에서만 검사한다(X64). 경고는 스키마 오류와 무관하게
  원본 데이터에서 계산할 수 있는 항목마다 계산한다(X65).
"""

from collections.abc import Iterable
from datetime import date
from pathlib import Path, PureWindowsPath
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from bid_deep_engine.company.hints import hint_for
from bid_deep_engine.company.provenance import (
    CompanyEvidenceView,
    ProvenanceDocument,
    encode_path_token,
    format_validation_errors,
    parse_canonical_path,
    resolve_profile_path,
    value_hash,
)
from bid_deep_engine.company.schema import (
    DATE_RE,
    LIST_ID_KEYS,
    ONSITE_KEYS,
    PORTFOLIO_ID_RE,
    UNKNOWN,
    CompanyProfile,
)


class ValidationReport(BaseModel):
    errors: list[str] = Field(default_factory=list)  # 하나라도 있으면 무효
    warnings: list[str] = Field(default_factory=list)  # 유효성에 영향 없음


class TodoItem(BaseModel):
    path: str  # canonical 점 경로 + `[인코딩 식별 키]` (예: `portfolio[P2026-01].amount_krw`)
    hint: str  # 확인처. 항상 비어 있지 않다(hint_for)
    level: str = UNKNOWN
    effective_level: str = UNKNOWN
    value_hash_matches: bool | None = None
    sources: list[dict[str, str]] = Field(default_factory=list)


class ProfileError(Exception):
    """load_profile 실패. errors는 validate의 errors와 같은 문구."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = list(errors)
        super().__init__("\n".join(self.errors))


def load_profile(path: Path | str) -> CompanyProfile:
    """실적이 병합된 프로필. 오류가 있으면 ProfileError(경고는 무시)."""
    profile, report, _ = _check(Path(path))
    if report.errors or profile is None:
        raise ProfileError(report.errors)
    return profile


def load_evidence_view(path: Path | str) -> CompanyEvidenceView:
    """프로필과 sidecar 출처 메타데이터를 검증해 읽기 뷰로 반환한다."""
    profile, report, provenance = _check(Path(path))
    if report.errors or profile is None:
        raise ProfileError(report.errors)
    return CompanyEvidenceView(profile, provenance, tuple(report.warnings))


def validate(path: Path | str) -> ValidationReport:
    """스키마·enum·날짜·금액·실적 ID 규칙 검사. 예외를 내지 않는다."""
    _, report, _ = _check(Path(path))
    return report


def todo(
    profile: CompanyProfile | CompanyEvidenceView,
    required_paths: Iterable[str] = (),
) -> list[TodoItem]:
    """미확인 값과 요청 경로를 나열하고, 뷰면 출처 미확인 원값도 포함한다."""
    view = profile if isinstance(profile, CompanyEvidenceView) else None
    raw_profile = view.profile if view is not None else profile
    paths: list[str] = []
    if view is not None:
        _collect_evidence_paths(raw_profile, "", paths)
        # 게이트·점수 단계가 필요하다고 판정한 경로도 출처 확인 대상에 포함한다.
        paths.extend(required_paths)
    else:
        _collect_unknown(raw_profile, "", paths)
    paths = list(dict.fromkeys(paths))

    items: list[TodoItem] = []
    for path in paths:
        if _is_structural_evidence_path(path):
            continue
        hint = hint_for(path)
        evidence = view.get(path) if view is not None else None
        if evidence is not None:
            if evidence["effective_level"] == "confirmed":
                continue
            hint = f"{hint} · 출처 확인 필요"
        items.append(
            TodoItem(
                path=path,
                hint=hint,
                **(
                    {
                        "level": evidence["level"],
                        "effective_level": evidence["effective_level"],
                        "value_hash_matches": evidence["value_hash_matches"],
                        "sources": evidence["sources"],
                    }
                    if evidence is not None
                    else {}
                ),
            )
        )
    return items


# --- 내부 ---

_MISSING = object()
_NOT_FOUND = "file not found:"


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys instead of overwriting them."""


def _construct_unique_mapping(loader: _UniqueKeyLoader, node: yaml.MappingNode, deep=False):
    loader.flatten_mapping(node)
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _check(
    path: Path,
) -> tuple[CompanyProfile | None, ValidationReport, ProvenanceDocument | None]:
    errors: list[str] = []
    warnings: list[str] = []

    raw, err = _read_yaml(path)
    if err is not None:
        # 프로필 파일 단위 오류도 "<파일 경로>: <내용>" 형식(spec validate API)
        return None, ValidationReport(errors=[f"{path}: {err}"], warnings=[]), None
    if not isinstance(raw, dict):
        return (
            None,
            ValidationReport(
                errors=[f"{path}: top-level must be a mapping (got {_kind(raw)})"], warnings=[]
            ),
            None,
        )
    raw = _dates_to_str(raw)
    warnings.extend(_onsite_warnings(raw))

    provenance_raw: Any = None
    provenance_error: str | None = None
    provenance_file = raw.get("provenance_file")
    if isinstance(provenance_file, str):
        provenance_path, provenance_error = _resolve_provenance_path(path, provenance_file)
        if provenance_path is not None:
            provenance_raw, provenance_error = _read_yaml(provenance_path)
            if provenance_error is None and not isinstance(provenance_raw, dict):
                provenance_error = f"top-level must be a mapping (got {_kind(provenance_raw)})"
        if provenance_error is not None:
            errors.append(f"provenance_file: {provenance_error}")

    provenance: ProvenanceDocument | None = None
    if provenance_raw is not None:
        try:
            provenance = ProvenanceDocument.model_validate(_dates_to_str(provenance_raw))
        except ValidationError as exc:
            errors.extend(format_validation_errors(exc))

    data = dict(raw)
    if "portfolio" in data:
        # portfolio는 로더가 portfolio_file에서 채우는 필드라 프로필 YAML에는 쓸 수 없다.
        del data["portfolio"]
        errors.append("portfolio: key not allowed in profile file (use portfolio_file)")

    portfolio_raw: list | None = None
    portfolio_errors: list[str] = []
    portfolio_file = raw.get("portfolio_file")
    if isinstance(portfolio_file, str):  # 아니면 스키마 오류로 보고되고 실적은 읽지 않는다
        loaded, err = _read_yaml(path.parent / portfolio_file)
        if err is not None:
            portfolio_errors.append(f"portfolio: {err}")
        elif not isinstance(loaded, list):
            portfolio_errors.append(
                f"portfolio: top-level must be a sequence (got {_kind(loaded)})"
            )
        else:
            portfolio_raw = _dates_to_str(loaded)
            data["portfolio"] = portfolio_raw

    profile: CompanyProfile | None = None
    try:
        profile = CompanyProfile.model_validate(data)
    except ValidationError as exc:
        errors.extend(_format_errors(exc.errors(include_url=False), data))
    errors.extend(portfolio_errors)

    if portfolio_raw is not None:
        id_errors, id_warnings = _check_portfolio_ids(portfolio_raw)
        errors.extend(id_errors)
        warnings.extend(id_warnings)

    errors.extend(_check_list_ids(data))
    if provenance is not None:
        provenance_errors, provenance_warnings = _validate_provenance_paths(profile, provenance)
        errors.extend(provenance_errors)
        warnings.extend(provenance_warnings)

    report = ValidationReport(errors=errors, warnings=warnings)
    return (None if errors else profile), report, provenance


def _resolve_provenance_path(
    profile_path: Path, relative_path: str
) -> tuple[Path | None, str | None]:
    """Resolve a sidecar only when its lexical and resolved paths stay beside the profile."""
    posix_path = Path(relative_path)
    windows_path = PureWindowsPath(relative_path)
    if (
        not relative_path
        or posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or ".." in posix_path.parts
        or ".." in windows_path.parts
    ):
        return None, "path must be relative to the profile directory and cannot traverse upward"
    profile_dir = profile_path.parent.resolve()
    target = profile_path.parent / posix_path
    try:
        resolved = target.resolve(strict=False)
        resolved.relative_to(profile_dir)
    except (OSError, RuntimeError, ValueError):
        return None, "path resolves outside the profile directory"
    return resolved, None


def _validate_provenance_paths(
    profile: CompanyProfile | None,
    provenance: ProvenanceDocument,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for path, entry in provenance.fields.items():
        try:
            parse_canonical_path(path)
        except ValueError as exc:
            errors.append(f"provenance.fields[{path}]: non-canonical path: {exc}")
            continue
        if profile is None:
            continue
        try:
            value = resolve_profile_path(profile, path)
        except ValueError as exc:
            errors.append(f"provenance.fields[{path}]: {exc}")
            continue
        if value_hash(value) != entry.value_hash:
            warnings.append(f"provenance.fields[{path}]: value_changed")
    return errors, warnings


def _read_yaml(path: Path) -> tuple[Any, str | None]:
    """(파싱 결과, 오류 문구). 빈 파일은 (None, None)."""
    if not path.is_file():
        return None, f"{_NOT_FOUND} {path}"
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"cannot read file: {_one_line(str(exc))}"
    try:
        return yaml.load(text, Loader=_UniqueKeyLoader), None
    except yaml.YAMLError as exc:
        return None, f"yaml parse error: {_one_line(str(exc))}"


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, dict):
        return "mapping"
    if isinstance(value, list):
        return "sequence"
    if isinstance(value, str):
        return "string"
    return type(value).__name__


def _dates_to_str(value: Any) -> Any:
    """PyYAML이 따옴표 없는 YYYY-MM-DD를 date로 읽으므로 검증 전에 문자열로 바꾼다."""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {_dates_to_str(k): _dates_to_str(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_dates_to_str(v) for v in value]
    return value


def _onsite_warnings(raw: dict) -> list[str]:
    """빠진 onsite_capacity 지역 키(모델이 "unknown"으로 채움). 매핑이 아니면 계산하지 않는다."""
    people = raw.get("people", {})
    if not isinstance(people, dict):
        return []
    onsite = people.get("onsite_capacity", {})
    if not isinstance(onsite, dict):
        return []
    return [
        f"people.onsite_capacity.{key}: missing, treated as unknown"
        for key in ONSITE_KEYS
        if key not in onsite
    ]


def _check_portfolio_ids(items: list) -> tuple[list[str], list[str]]:
    """실적 ID 형식 오류와 경고 1(ID 연도 ≠ period.start 연도)."""
    errors: list[str] = []
    warnings: list[str] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        pid = item.get("id")
        if not isinstance(pid, str):  # 없거나 문자열이 아니면 스키마 오류 한 줄로 충분
            continue
        if not PORTFOLIO_ID_RE.fullmatch(pid):
            errors.append(
                f"portfolio[#{idx}].id: invalid id '{pid}' (expected {PORTFOLIO_ID_RE.pattern})"
            )
            continue
        period = item.get("period")
        start = period.get("start") if isinstance(period, dict) else None
        if isinstance(start, str) and DATE_RE.fullmatch(start) and start[:4] != pid[1:5]:
            warnings.append(
                f"portfolio[{pid}].id: id year {pid[1:5]} != period.start year {start[:4]}"
            )
    return errors, warnings


def _check_list_ids(data: dict) -> list[str]:
    """모든 LIST_ID_KEYS 목록에서 문자열 식별자의 중복을 검출한다."""
    errors: list[str] = []
    for list_path, id_key in LIST_ID_KEYS.items():
        value: Any = data
        for part in list_path.split("."):
            if not isinstance(value, dict) or part not in value:
                value = None
                break
            value = value[part]
        if not isinstance(value, list):
            continue
        seen: set[str] = set()
        for item in value:
            if not isinstance(item, dict):
                continue
            identifier = item.get(id_key)
            if not isinstance(identifier, str) or not identifier.strip():
                continue
            if identifier in seen:
                canonical_list = ".".join(encode_path_token(part) for part in list_path.split("."))
                canonical_id = encode_path_token(identifier)
                canonical_key = encode_path_token(id_key)
                errors.append(f"{canonical_list}[{canonical_id}].{canonical_key}: duplicate id")
            seen.add(identifier)
    return errors


# --- todo 경로 수집 ---


def _collect_unknown(value: Any, path: str, out: list[str]) -> None:
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            _collect_unknown(getattr(value, name), _join_path(path, name), out)
    elif isinstance(value, dict):  # 사전 키는 그대로(연도 int도 문자열로)
        for key, item in value.items():
            _collect_unknown(item, _join_path(path, str(key)), out)
    elif isinstance(value, list):
        id_key = LIST_ID_KEYS.get(path)
        if id_key is None:
            if any(_contains_unknown(item) for item in value):
                out.append(path)
            return
        for idx, item in enumerate(value):
            _collect_unknown(item, f"{path}[{_todo_label(item, id_key, idx)}]", out)
    elif value == UNKNOWN:
        out.append(path)


_STRUCTURAL_PROFILE_FIELDS = {"schema_version", "portfolio_file", "provenance_file"}


def _collect_evidence_paths(value: Any, path: str, out: list[str]) -> None:
    """Collect source-bearing canonical paths without list positions or identity fields."""
    if isinstance(value, BaseModel):
        for name in type(value).model_fields:
            if not path and name in _STRUCTURAL_PROFILE_FIELDS:
                continue
            _collect_evidence_paths(getattr(value, name), _join_path(path, name), out)
        return
    if isinstance(value, dict):
        if not value:
            if path:
                out.append(path)
            return
        for key, item in value.items():
            _collect_evidence_paths(item, _join_path(path, str(key)), out)
        return
    if isinstance(value, list):
        if not path:
            return
        out.append(path)  # list completeness is a separate source-bearing value
        id_key = LIST_ID_KEYS.get(path)
        if id_key is None:
            return  # lists without stable identifiers use the list path, never positions
        for index, item in enumerate(value):
            label = _todo_label(item, id_key, index)
            item_path = f"{path}[{label}]"
            if isinstance(item, BaseModel):
                for name in type(item).model_fields:
                    if name == id_key:
                        continue
                    _collect_evidence_paths(getattr(item, name), _join_path(item_path, name), out)
            else:
                _collect_evidence_paths(item, item_path, out)
        return
    if path:
        out.append(path)


def _is_structural_evidence_path(path: str) -> bool:
    """Exclude schema/file pointers and stable list IDs from provenance TODOs."""
    try:
        parts = parse_canonical_path(path)
    except ValueError:
        return False
    if len(parts) == 1 and parts[0][0] in _STRUCTURAL_PROFILE_FIELDS:
        return True
    field_path: list[str] = []
    previous_id: str | None = None
    previous_list_path: str | None = None
    for index, (field, identifier) in enumerate(parts):
        if index > 0 and previous_id is not None and previous_list_path is not None:
            if LIST_ID_KEYS.get(previous_list_path) == field and index == len(parts) - 1:
                return True
        field_path.append(field)
        previous_id = identifier
        previous_list_path = ".".join(field_path) if identifier is not None else None
    return False


def _join_path(path: str, name: str) -> str:
    encoded = encode_path_token(name)
    return f"{path}.{encoded}" if path else encoded


def _todo_label(item: Any, id_key: str | None, idx: int) -> str:
    """식별 키 값이 비어 있지 않은 문자열이면 그 값, 아니면 0부터 인덱스."""
    if id_key is not None and isinstance(item, BaseModel):
        value = getattr(item, id_key, None)
        if isinstance(value, str) and value.strip():
            return encode_path_token(value)
    return str(idx)


def _contains_unknown(value: Any) -> bool:
    if isinstance(value, BaseModel):
        return any(_contains_unknown(getattr(value, name)) for name in type(value).model_fields)
    if isinstance(value, dict):
        return any(_contains_unknown(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_unknown(item) for item in value)
    return value == UNKNOWN


# --- pydantic 오류 → 오류 줄 ---


def _format_errors(errs: list[dict[str, Any]], data: dict) -> list[str]:
    """경로당 한 줄. union 분기 오류는 태그를 경로에서 빼고 첫 메시지 + 허용 목록으로 합친다."""
    groups: dict[str, list[tuple[str, str, str | None]]] = {}
    for err in errs:
        key, path, branch = _locate(err, data)
        groups.setdefault(key, []).append((path, err["msg"], branch))
    lines = []
    for entries in groups.values():
        path, msg, _ = entries[0]
        branches = list(dict.fromkeys(b for _, _, b in entries if b is not None))
        line = f"{path}: {msg}"
        if branches:
            line += "; 허용: " + ", ".join(_branch_name(b) for b in branches)
        lines.append(line)
    return lines


def _locate(err: dict[str, Any], data: Any) -> tuple[str, str, str | None]:
    """(묶음 키, 출력 경로, 첫 union 분기 태그).

    loc를 원본 데이터와 함께 따라간다. 데이터에 있는 키·인덱스와 마지막 missing 필드는 경로이고,
    나머지 문자열은 pydantic union 분기 태그(`constrained-int`, `literal['unknown']` 등)다.
    묶음 키는 union이면 첫 태그 앞 경로(union 필드), 아니면 출력 경로.
    """
    loc = err["loc"]
    node = data
    segs: list[str] = []  # 출력 경로 조각
    pattern: list[str] = []  # LIST_ID_KEYS 조회용(인덱스 = [*])
    group: str | None = None
    branch: str | None = None
    for pos, el in enumerate(loc):
        if el == "[key]":  # dict 키 검증 태그
            continue
        if isinstance(node, list) and type(el) is int and 0 <= el < len(node):
            item = node[el]
            segs.append(_index_label(_join(pattern), item, el))
            pattern.append("[*]")
            node = item
        elif isinstance(node, dict) and el in node:
            segs.append(str(el))
            pattern.append(str(el))
            node = node[el]
        elif err["type"] == "missing" and pos == len(loc) - 1:
            segs.append(str(el))
        elif group is None:
            group = _join(segs)
            branch = str(el)
        # 중첩 union의 안쪽 태그는 경로에서 빼기만 한다.
    path = _join(segs)
    return (group if group is not None else path), path, branch


def _join(segs: list[str]) -> str:
    out = ""
    for seg in segs:
        out += seg if seg.startswith("[") or not out else f".{seg}"
    return out


def _index_label(list_path: str, item: Any, idx: int) -> str:
    key = LIST_ID_KEYS.get(list_path)
    if key is not None and isinstance(item, dict):
        value = item.get(key, _MISSING)
        if isinstance(value, str) and value.strip():
            if list_path != "portfolio" or PORTFOLIO_ID_RE.fullmatch(value):
                return f"[{value}]"
    return f"[#{idx}]"


def _branch_name(tag: str) -> str:
    """pydantic union 분기 태그 → 허용 목록 표기."""
    if tag == "constrained-str":
        return "YYYY-MM|YYYY-MM-DD"  # union 안의 제약 문자열은 DateStr뿐
    if tag.startswith("literal[") and tag.endswith("]"):
        return ", ".join(tag[len("literal[") : -1].split(","))
    return tag.replace("constrained-", "").replace(",", ", ")
