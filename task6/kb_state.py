#!/usr/bin/env python3
"""
  python3 task6/kb_state.py scan --kb-dir task2/knowledge_base
  python3 task6/kb_state.py scan --kb-dir task2/knowledge_base --state task6/kb_sync_state.json
  python3 task6/kb_state.py scan --kb-dir task2/knowledge_base --format plain
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_STATE_NAME = "kb_sync_state.json"


def sha256_file(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def scan_kb_hashes(kb_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not kb_dir.is_dir():
        return out
    for p in sorted(kb_dir.glob("*.md")):
        if p.is_file():
            rel = str(p.relative_to(kb_dir))
            out[rel] = sha256_file(p)
    return out


def load_state(state_path: Path) -> dict[str, str]:
    if not state_path.is_file():
        return {}
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        files = data.get("files")
        if isinstance(files, dict):
            return {str(k): str(v) for k, v in files.items()}
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def save_state(state_path: Path, files: dict[str, str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"files": files, "updated_at": datetime.now(timezone.utc).isoformat()}, indent=2),
        encoding="utf-8",
    )


def count_changes(prev: dict[str, str], curr: dict[str, str]) -> tuple[int, int, int]:
    prev_keys = set(prev)
    curr_keys = set(curr)
    new_files = sum(1 for k in curr_keys - prev_keys)
    deleted = len(prev_keys - curr_keys)
    changed = sum(1 for k in curr_keys & prev_keys if prev[k] != curr[k])
    return new_files, changed, deleted


def cmd_scan(args: argparse.Namespace) -> None:
    kb_dir: Path = args.kb_dir
    state_path: Path = args.state

    if not kb_dir.is_dir():
        print(f"Каталог не найден: {kb_dir}", file=sys.stderr)
        raise SystemExit(1)

    prev = load_state(state_path)
    curr = scan_kb_hashes(kb_dir)
    new_n, changed_n, deleted_n = count_changes(prev, curr)
    save_state(state_path, curr)

    out = {
        "files_new": new_n,
        "files_changed": changed_n,
        "files_deleted": deleted_n,
    }
    if args.format == "plain":
        print(new_n, changed_n, deleted_n)
    else:
        print(json.dumps(out, ensure_ascii=False))


def main() -> None:
    p = argparse.ArgumentParser(description="SHA-256 и kb_sync_state.json для каталога .md")
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("scan", help="Пересчитать хеши, обновить state, вывести JSON со счётчиками")
    ps.add_argument("--kb-dir", type=Path, required=True)
    ps.add_argument(
        "--state",
        type=Path,
        default=None,
        help=f"Путь к JSON состояния (по умолчанию: рядом со скриптом — {DEFAULT_STATE_NAME})",
    )
    ps.add_argument(
        "--format",
        choices=("json", "plain"),
        default="json",
        help="json — одна строка JSON; plain — три числа через пробел (для read в bash)",
    )
    ps.set_defaults(func=cmd_scan)

    args = p.parse_args()
    if args.command == "scan" and args.state is None:
        args.state = Path(__file__).resolve().parent / DEFAULT_STATE_NAME
    args.func(args)


if __name__ == "__main__":
    main()
