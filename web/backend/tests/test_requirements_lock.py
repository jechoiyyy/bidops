from __future__ import annotations

from importlib.metadata import distributions
from pathlib import Path
import re

from packaging.requirements import Requirement


BACKEND = Path(__file__).resolve().parents[1]
DIRECT_REQUIREMENTS = BACKEND / "requirements.txt"
LOCKFILE = BACKEND / "requirements.lock"
_LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;]+)$")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _direct_requirements() -> dict[str, Requirement]:
    requirements: dict[str, Requirement] = {}
    for raw_line in DIRECT_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        requirement = Requirement(line)
        name = _normalize(requirement.name)
        assert name not in requirements, f"duplicate direct requirement: {name}"
        requirements[name] = requirement
    return requirements


def _locked_versions() -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in LOCKFILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        assert match is not None, f"lock entry is not an exact pin: {raw_line!r}"
        name = _normalize(match.group(1))
        assert name not in versions, f"duplicate lock entry: {name}"
        versions[name] = match.group(2)
    return versions


def test_direct_requirements_are_exactly_covered_by_installed_lock() -> None:
    locked = _locked_versions()
    direct = _direct_requirements()
    missing = set(direct) - locked.keys()
    assert not missing, f"direct requirements missing from lock: {sorted(missing)}"
    incompatible = {
        name: (str(requirement.specifier), locked[name])
        for name, requirement in direct.items()
        if locked[name] not in requirement.specifier
    }
    assert not incompatible, f"lock versions violate direct requirements: {incompatible}"

    installed = {
        _normalize(metadata["Name"]): metadata["Version"]
        for distribution in distributions()
        if (metadata := distribution.metadata).get("Name")
    }
    missing_installed = set(locked) - set(installed)
    assert not missing_installed, f"locked distributions are not installed: {sorted(missing_installed)}"
    drift = {
        name: (locked[name], installed[name])
        for name in locked
        if installed[name] != locked[name]
    }
    assert not drift, f"installed dependency versions drifted from lock: {drift}"
