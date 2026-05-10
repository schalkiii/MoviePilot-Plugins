#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

show_help() {
  cat <<'EOF'
Usage:
  bash scripts/print-skill-release-summary.sh

Prints a Markdown table for public Skill ZIP release assets from
dist/skills/MANIFEST.json.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

python3 - <<'PY'
import json
from pathlib import Path

manifest_file = Path("dist/skills/MANIFEST.json")
if not manifest_file.exists():
    print("dist/skills/MANIFEST.json 不存在")
    raise SystemExit(1)
manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
skills = manifest.get("skills") or []
print("| Skill | Version | ZIP | SHA256 |")
print("| --- | --- | --- | --- |")
for item in skills:
    print(
        "| {id} | {version} | `{zip}` | `{sha}` |".format(
            id=item.get("id", ""),
            version=item.get("version", ""),
            zip=item.get("zip", ""),
            sha=str(item.get("sha256", ""))[:12],
        )
    )
PY
