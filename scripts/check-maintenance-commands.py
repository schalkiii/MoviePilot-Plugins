#!/usr/bin/env python3
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

HELP_SHELL_SCRIPTS = [
    "scripts/repo-hygiene.sh",
    "scripts/release-preflight.sh",
    "scripts/pre-release-check.sh",
    "scripts/check-skills.sh",
    "scripts/clean-generated.sh",
    "scripts/package-plugin.sh",
    "scripts/package-skills.sh",
    "scripts/sync-repo-layout.sh",
    "scripts/sync-package-v2.sh",
    "scripts/create-draft-release.sh",
    "scripts/update-draft-release-assets.sh",
    "scripts/generate-release-notes.sh",
    "scripts/write-dist-sha256.sh",
    "scripts/patch-p115strmhelper-mp-compat.sh",
    "scripts/verify-release-preflight-artifact.sh",
    "scripts/verify-ci-artifact.sh",
    "scripts/verify-release-download.sh",
    "scripts/verify-release-assets.sh",
    "scripts/verify-dist.sh",
    "scripts/verify-skill-dist.sh",
    "scripts/print-release-summary.sh",
    "scripts/print-skill-release-summary.sh",
]

HELP_PYTHON_SCRIPTS = [
    "scripts/check-doc-current-state.py",
    "scripts/audit-remote-branches.py",
    "scripts/archive-local-branches.py",
]


def show_help() -> None:
    print(
        "Usage:\n"
        "  python3 scripts/check-maintenance-commands.py\n\n"
        "Checks that high-frequency maintenance scripts support --help and that\n"
        "docs/MAINTENANCE_COMMANDS.md lists the same commands."
    )


def run_help(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] in {"--help", "-h"}:
        show_help()
        return 0

    maintenance_doc = (ROOT / "docs/MAINTENANCE_COMMANDS.md").read_text(encoding="utf-8")
    missing: list[str] = []

    for rel_path in HELP_SHELL_SCRIPTS:
        run_help(["bash", rel_path, "--help"])
        name = Path(rel_path).name
        if f"`{name}`" not in maintenance_doc:
            missing.append(name)

    for rel_path in HELP_PYTHON_SCRIPTS:
        run_help(["python3", rel_path, "--help"])
        name = Path(rel_path).name
        if f"`{name}`" not in maintenance_doc:
            missing.append(name)

    if missing:
        print("docs/MAINTENANCE_COMMANDS.md 缺少帮助脚本清单:")
        for name in missing:
            print(name)
        return 1

    count = len(HELP_SHELL_SCRIPTS) + len(HELP_PYTHON_SCRIPTS)
    print(f"maintenance_commands_ok count={count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
