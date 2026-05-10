#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  bash scripts/verify-release-preflight-artifact.sh --help
  exit 0
fi

echo "warning: scripts/verify-ci-artifact.sh 已弃用，请改用 scripts/verify-release-preflight-artifact.sh" >&2
exec bash scripts/verify-release-preflight-artifact.sh "$@"
