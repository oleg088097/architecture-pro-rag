#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

VENV="${VENV:-${REPO_ROOT}/.venv}"
if [[ ! -f "${VENV}/bin/activate" ]]; then
  echo "update_cron.sh: не найден ${VENV}/bin/activate" >&2
  exit 1
fi
# shellcheck source=/dev/null
. "${VENV}/bin/activate"

exec "${SCRIPT_DIR}/update.sh"
