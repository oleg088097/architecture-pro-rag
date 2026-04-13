#!/usr/bin/env bash
#   ./task6/update.sh
#   KB_DIR=/path/to/md CHROMA_DIR=/path/to/chroma ./task6/update.sh
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)" || exit
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)" || exit
cd "${REPO_ROOT}" || exit

export PYTHONPATH="${REPO_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

KB_DIR="${KB_DIR:-${REPO_ROOT}/task2/knowledge_base}"
CHROMA_DIR="${CHROMA_DIR:-${REPO_ROOT}/task3/chroma_data}"
BATCH_SIZE="${BATCH_SIZE:-16}"
STATE_FILE="${STATE_FILE:-${SCRIPT_DIR}/kb_sync_state.json}"

mkdir -p "${SCRIPT_DIR}/logs" || exit
RUN_STAMP="$(date -u +"%Y-%m-%dT%H-%M-%SZ")"
STARTED_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
LOG_TXT="${SCRIPT_DIR}/logs/update_${RUN_STAMP}.log"

# Печатает заголовок и содержимое файла с отступом (для блока ошибок в логе).
append_log_indented_block() {
  local heading="$1"
  local path="$2"
  echo ""
  echo "${heading}"
  sed 's/^/  /' "${path}"
}

# Лог при падении kb_state.py: нужны STARTED_ISO, LOG_TXT (глобальные).
log_write_kb_state_error() {
  local finished="$1"
  local code="$2"
  local detail_path="$3"
  {
    echo "started_at: ${STARTED_ISO}"
    echo "finished_at: ${finished}"
    echo "summary: kb_state.py scan failed (exit ${code})"
    append_log_indented_block "errors:" "${detail_path}"
  } >"${LOG_TXT}" || true
  echo "Log: ${LOG_TXT}" >&2
}

# Итоговый лог прогона: при idx_exit≠0 добавляет сообщение и вывод build_index.
log_write_run_log() {
  local finished="$1"
  local summary="$2"
  local idx_exit="$3"
  local build_out_path="${4:-}"
  {
    echo "started_at: ${STARTED_ISO}"
    echo "finished_at: ${finished}"
    echo "${summary}"
    if [[ "${idx_exit}" -ne 0 ]]; then
      echo ""
      echo "errors:"
      echo "  - build_index.py exited with code ${idx_exit}"
      append_log_indented_block "build_index output (stdout/stderr):" "${build_out_path}"
    fi
  } >"${LOG_TXT}" || exit
  echo "Log: ${LOG_TXT}" >&2
}

SCAN_TMP="$(mktemp)" || exit
TMP_OUT=""
cleanup() {
  [[ -n "${SCAN_TMP}" ]] && rm -f "${SCAN_TMP}"
  [[ -n "${TMP_OUT}" ]] && rm -f "${TMP_OUT}"
}
trap cleanup EXIT

python3 "${SCRIPT_DIR}/kb_state.py" scan --kb-dir "${KB_DIR}" --state "${STATE_FILE}" --format plain \
  >"${SCAN_TMP}" 2>&1
KS_EXIT=$?

if [[ "${KS_EXIT}" -ne 0 ]]; then
  log_write_kb_state_error "$(date -u +"%Y-%m-%dT%H:%M:%SZ")" "${KS_EXIT}" "${SCAN_TMP}"
  exit "${KS_EXIT}"
fi

read -r FILES_NEW FILES_CHANGED FILES_DELETED <<<"$(head -n 1 "${SCAN_TMP}")"
rm -f "${SCAN_TMP}"
SCAN_TMP=""

TMP_OUT="$(mktemp)" || exit

python3 "${REPO_ROOT}/task3/build_index.py" index \
  --kb-dir "${KB_DIR}" \
  --chroma-dir "${CHROMA_DIR}" \
  --batch-size "${BATCH_SIZE}" \
  --reset 2>&1 | tee "${TMP_OUT}"
IDX_EXIT="${PIPESTATUS[0]}"

CHUNKS_LINE="$(grep 'Документов (чанков):' "${TMP_OUT}" | tail -1 || true)"
INDEX_SIZE="$(sed -n 's/.*: *\([0-9][0-9]*\).*/\1/p' <<<"${CHUNKS_LINE}" | head -1)"
[[ -n "${INDEX_SIZE}" ]] || INDEX_SIZE=""

FINISHED_ISO="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
FINISHED_HUMAN="$(date -u +"%Y-%m-%d %H:%M:%S")"

SUMMARY_LINE="index updated at ${FINISHED_HUMAN} UTC, ${FILES_NEW} files new, ${FILES_CHANGED} files changed, ${FILES_DELETED} removed from KB, index_size=${INDEX_SIZE}, build_index_exit=${IDX_EXIT}"

log_write_run_log "${FINISHED_ISO}" "${SUMMARY_LINE}" "${IDX_EXIT}" "${TMP_OUT}"

echo "${SUMMARY_LINE}"

if [[ "${IDX_EXIT}" -ne 0 ]]; then
  exit "${IDX_EXIT}"
fi
