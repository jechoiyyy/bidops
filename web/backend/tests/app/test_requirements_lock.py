from __future__ import annotations

from importlib.metadata import PackageNotFoundError, distribution, distributions
from pathlib import Path
import re

import pytest
from packaging.markers import default_environment
from packaging.requirements import Requirement


BACKEND = Path(__file__).resolve().parents[2]
CONTAINER_BACKEND = Path("/app/web/backend")
DIRECT_REQUIREMENTS = BACKEND / "requirements.txt"
LOCKFILE = BACKEND / "requirements.lock"
BOOTSTRAP_DISTRIBUTIONS = frozenset({"pip"})
_LOCK_LINE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.-]+)==(?P<version>[^\s]+)"
    r"(?P<hashes>(?:\s+--hash=sha256:[0-9a-f]{64})+)$"
)
_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})$")


def _normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).casefold()


def _target_marker_environment() -> dict[str, str]:
    environment = default_environment()
    environment.update(
        {
            "implementation_name": "cpython",
            "python_full_version": "3.12.14",
            "python_version": "3.12",
            "platform_machine": "x86_64",
            "platform_system": "Linux",
            "sys_platform": "linux",
        }
    )
    return environment


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


def _locked_versions() -> dict[str, tuple[str, tuple[str, ...]]]:
    locked: dict[str, tuple[str, tuple[str, ...]]] = {}
    for raw_line in LOCKFILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LOCK_LINE.fullmatch(line)
        assert match is not None, f"lock entry is not canonical and hash-pinned: {raw_line!r}"
        name = _normalize(match.group("name"))
        assert name not in locked, f"duplicate lock entry: {name}"
        hashes = tuple(_HASH.fullmatch(token).group(1) for token in match.group("hashes").split())
        assert len(hashes) == len(set(hashes)), f"duplicate artifact hash: {name}"
        locked[name] = (match.group("version"), hashes)
    return locked


def _active_direct_requirements() -> dict[str, Requirement]:
    environment = _target_marker_environment()
    return {
        name: requirement
        for name, requirement in _direct_requirements().items()
        if requirement.marker is None or requirement.marker.evaluate(environment)
    }


def test_lock_is_canonical_and_covers_target_direct_requirements() -> None:
    locked = _locked_versions()
    names = list(locked)
    assert names == sorted(names), "lock entries must be sorted by normalized distribution name"

    direct = _active_direct_requirements()
    missing = set(direct) - locked.keys()
    assert not missing, f"active direct requirements missing from lock: {sorted(missing)}"
    incompatible = {
        name: (str(requirement.specifier), locked[name][0])
        for name, requirement in direct.items()
        if locked[name][0] not in requirement.specifier
    }
    assert not incompatible, f"lock versions violate direct requirements: {incompatible}"


def _installed_versions() -> dict[str, str]:
    installed: dict[str, str] = {}
    for package in distributions():
        metadata = package.metadata
        name = metadata.get("Name")
        if not name:
            continue
        normalized = _normalize(name)
        assert normalized not in installed, f"duplicate installed distribution: {normalized}"
        installed[normalized] = metadata["Version"]
    return installed


def _dependency_closure(direct: dict[str, Requirement]) -> set[str]:
    environment = _target_marker_environment()
    pending = [(name, frozenset(requirement.extras)) for name, requirement in direct.items()]
    visited: set[tuple[str, frozenset[str]]] = set()
    closure: set[str] = set()

    while pending:
        name, extras = pending.pop()
        state = (name, extras)
        if state in visited:
            continue
        visited.add(state)
        closure.add(name)
        try:
            requirements = distribution(name).requires or ()
        except PackageNotFoundError as exc:
            raise AssertionError(f"closure distribution is not installed: {name}") from exc

        for raw_requirement in requirements:
            requirement = Requirement(raw_requirement)
            for extra in (None, *sorted(extras)):
                marker_environment = dict(environment)
                marker_environment["extra"] = extra or ""
                if requirement.marker is not None and not requirement.marker.evaluate(marker_environment):
                    continue
                dependency = _normalize(requirement.name)
                dependency_extras = frozenset(requirement.extras)
                closure.add(dependency)
                pending.append((dependency, dependency_extras))
    return closure


def test_container_dependency_set_matches_lock_without_unapproved_extras() -> None:
    """Run installed-set checks only in the image's explicit /app boundary.

    A developer venv may contain unrelated tools. The image has the lock as its
    complete application/test environment, with pip as the sole bootstrap
    exception. Direct extras (currently uvicorn[standard]) are traversed into
    the expected closure rather than permitting arbitrary installed packages.
    """

    if BACKEND != CONTAINER_BACKEND:
        pytest.skip("installed-set assertion is scoped to the target container path")

    locked = _locked_versions()
    installed = _installed_versions()
    application_installed = set(installed) - BOOTSTRAP_DISTRIBUTIONS
    unexpected = application_installed - set(locked)
    missing = set(locked) - application_installed
    assert not unexpected, f"installed distributions outside lock: {sorted(unexpected)}"
    assert not missing, f"locked distributions are not installed: {sorted(missing)}"
    drift = {
        name: (locked[name][0], installed[name])
        for name in locked
        if installed[name] != locked[name][0]
    }
    assert not drift, f"installed dependency versions drifted from lock: {drift}"

    closure = _dependency_closure(_active_direct_requirements())
    assert closure == set(locked), {
        "missing_from_lock": sorted(closure - set(locked)),
        "unrequired_lock_entries": sorted(set(locked) - closure),
    }
