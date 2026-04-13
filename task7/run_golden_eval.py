#!/usr/bin/env python3
"""
  python task7/run_golden_eval.py
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import re
import sys
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK7 = Path(__file__).resolve().parent
REPO = TASK7.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

REFUSAL = re.compile(
    r"(?is)\b("
    r"i\s+don'?t\s+know|don'?t\s+have|no\s+information|cannot\s+answer|not\s+in\s+the\s+context|"
    r"не\s+знаю|нет\s+(данных|информации)|недостаточно|не\s+могу\s+ответить|"
    r"информации\s+в\s+(базе|контексте)\s+нет|в\s+контексте\s+не\s+указано"
    r")\b",
)

MIN_ANSWER_LEN = 32


def looks_like_refusal(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return True
    if REFUSAL.search(t):
        return True
    low = t.lower()
    if "don't know" in low and len(t) < 400:
        return True
    return False


def keywords_hit(answer: str, keywords: list[str]) -> tuple[bool, list[str]]:
    """Все подстроки из must_mention должны встретиться (без учёта регистра)."""
    a = answer or ""
    missing = [k for k in keywords if k.lower() not in a.lower()]
    return (len(missing) == 0, missing)


def completeness_answer(chunks_found: bool, refusal: bool, kw_ok: bool) -> float:
    score = 0.0
    if chunks_found:
        score += 0.35
    if not refusal:
        score += 0.35
    if kw_ok:
        score += 0.30
    return round(min(1.0, score), 3)


def evaluate_answer_expectation(
    expect: str,
    answer: str,
    chunks_found: bool,
    must_mention: list[str] | None,
) -> dict[str, Any]:
    must_mention = must_mention or []
    refusal = looks_like_refusal(answer)
    kw_ok, missing_kw = keywords_hit(answer, must_mention)

    if expect == "answer":
        ok = (
            chunks_found
            and not refusal
            and len((answer or "").strip()) >= MIN_ANSWER_LEN
            and kw_ok
        )
        comp = completeness_answer(chunks_found, refusal, kw_ok)
        return {
            "expected": "answer",
            "pass": ok,
            "answer_found": chunks_found and not refusal,
            "completeness": comp,
            "keywords_matched": kw_ok,
            "keywords_missing": missing_kw,
            "refusal_detected": refusal,
        }

    # abstain: корректно — явный отказ / неуверенность, или нет чанков; плохо — уверенный длинный ответ при наличии чанков
    if refusal:
        ok = True
        comp = 0.85
    elif not chunks_found:
        ok = True
        comp = 0.7 if len((answer or "").strip()) < 400 else 0.4
    else:
        long_confident = len((answer or "").strip()) > 180 and not refusal
        ok = not long_confident
        comp = 0.35 if ok else 0.1

    return {
        "expected": "abstain",
        "pass": ok,
        "answer_found": chunks_found and not refusal,
        "completeness": comp,
        "keywords_matched": None,
        "keywords_missing": [],
        "refusal_detected": refusal,
        "risk_hallucination": chunks_found and not refusal and len((answer or "").strip()) > 180,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden-set evaluation for task7/bot.py")
    parser.add_argument(
        "--golden",
        type=Path,
        default=TASK7 / "golden_questions.json",
        help="JSON с полем items[]",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="JSON-отчёт (по умолчанию task7/logs/golden_eval_<utc>.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Не импортировать bot / не вызывать LLM; проверить только разбор golden JSON",
    )
    args = parser.parse_args()

    data = json.loads(args.golden.read_text(encoding="utf-8"))
    items: list[dict[str, Any]] = data["items"]

    out_path = args.output
    if out_path is None:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_path = TASK7 / "logs" / f"golden_eval_{stamp}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        report = {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "golden_file": str(args.golden),
            "dry_run": True,
            "items": [{"id": it["id"], "question": it["question"], "expect": it["expect"]} for it in items],
            "summary": {"total": len(items), "passed": 0, "failed": 0},
        }
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report["summary"], ensure_ascii=False))
        return

    logging.getLogger().setLevel(logging.WARNING)

    from task7.bot import run_query

    results: list[dict[str, Any]] = []
    passed = 0
    failed = 0

    for it in items:
        q = it["question"]
        expect = it["expect"]
        must = it.get("must_mention")

        buf = io.StringIO()
        with redirect_stdout(buf):
            payload = run_query(q)

        merged = {
            "id": it["id"],
            "question": q,
            "expect": expect,
            "must_mention": must,
            "answer": payload.get("answer"),
            "bot": {k: v for k, v in payload.items() if k != "answer"},
        }

        ev = evaluate_answer_expectation(
            expect,
            payload.get("answer") or "",
            bool(payload.get("chunks_found")),
            must if isinstance(must, list) else None,
        )
        merged["evaluation"] = ev
        merged["bot"]["answer_length"] = payload.get("answer_length")
        if ev["pass"]:
            passed += 1
        else:
            failed += 1

        results.append(merged)

    report = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "golden_file": str(args.golden.resolve()),
        "dry_run": False,
        "summary": {
            "total": len(items),
            "passed": passed,
            "failed": failed,
            "pass_rate": round(passed / len(items), 4) if items else 0.0,
        },
        "items": results,
    }

    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print("Report:", out_path)


if __name__ == "__main__":
    main()
