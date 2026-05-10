#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> str:
    completed = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def local_branches() -> list[str]:
    output = run("git", "branch", "--format", "%(refname:short)")
    return [branch.strip() for branch in output.splitlines() if branch.strip() and branch.strip() != "main"]


def tag_exists(tag: str) -> bool:
    completed = subprocess.run(
        ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0


def archive_plan() -> list[dict[str, str | bool]]:
    plan = []
    for branch in local_branches():
        tag = f"archive/{branch}"
        plan.append(
            {
                "branch": branch,
                "tag": tag,
                "tag_exists": tag_exists(tag),
            }
        )
    return plan


def apply_plan(plan: list[dict[str, str | bool]]) -> None:
    for item in plan:
        branch = str(item["branch"])
        tag = str(item["tag"])
        if not item["tag_exists"]:
            subprocess.run(
                ["git", "tag", "-a", tag, branch, "-m", f"Archive local branch {branch} before cleanup"],
                cwd=ROOT,
                check=True,
            )
        subprocess.run(["git", "branch", "-D", branch], cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive local non-main branches into local archive/* tags.")
    parser.add_argument("--apply", action="store_true", help="Create archive tags and delete local branches.")
    args = parser.parse_args()

    plan = archive_plan()
    payload = {
        "mode": "apply" if args.apply else "dry_run",
        "count": len(plan),
        "branches": plan,
    }

    if args.apply:
        apply_plan(plan)
        payload["result"] = "applied"

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
