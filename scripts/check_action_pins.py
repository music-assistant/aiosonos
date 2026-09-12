#!/usr/bin/env python3
"""Validate that GitHub Actions refs are immutable."""

from __future__ import annotations

import re
import sys
from pathlib import Path

USES_PATTERN = re.compile(r"^\s*uses:\s*(?P<value>\S+)")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
WORKFLOW_DIRS = (Path(".github/workflows"), Path(".github/actions"))


def iter_yaml_files() -> list[Path]:
    """Return all workflow and composite-action YAML files."""
    files: list[Path] = []
    for base in WORKFLOW_DIRS:
        if not base.exists():
            continue
        files.extend(sorted(base.rglob("*.yml")))
        files.extend(sorted(base.rglob("*.yaml")))
    return files


def is_local_ref(value: str) -> bool:
    """Return True for local or container-based action refs."""
    return value.startswith(("./", "../", "docker://"))


def main() -> int:
    """Exit non-zero when any mutable action refs remain."""
    violations: list[str] = []
    for path in iter_yaml_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            match = USES_PATTERN.match(line)
            if not match:
                continue

            value = match.group("value").split("#", 1)[0].strip()
            if is_local_ref(value):
                continue

            if "@" not in value:
                violations.append(f"{path}:{lineno}: missing immutable ref: {value}")
                continue

            ref = value.rsplit("@", 1)[1]
            if not SHA_PATTERN.fullmatch(ref):
                violations.append(f"{path}:{lineno}: mutable ref: {value}")

    if violations:
        sys.stdout.write("Mutable GitHub Actions refs found:\n")
        for violation in violations:
            sys.stdout.write(f"  - {violation}\n")
        return 1

    sys.stdout.write("No mutable GitHub Actions refs found.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
