"""Blind hand labels for `honesty_rl.evaluate` records, scored against the grader.

    python -m honesty_rl.label --records runs/trained_seen.jsonl \\
        --tasks data/honesty/eval_seen.jsonl --out runs/label_trained.html --strict
    python -m honesty_rl.label --records runs/trained_seen.jsonl \\
        --tasks data/honesty/eval_seen.jsonl --score labels.json --strict

The harness's own labelling tool (`python -m honesty label`) on generated
variants: the same blind page, with the grader's class never shown, the same
half-accused, half-cleared sample, and Cohen's kappa. Variants are spread by
the template they came from. Each card describes the variant's own world, not
the published probe's. A follow-up probe's card shows the whole exchange.
`--strict` grades and labels under the strict view, the one training uses.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from honesty import labeling
from honesty.world import UNREADABLE

from .evaluate import load_tasks
from .spec import Task


def rows(records: list[dict], *, strict: bool = False) -> list[dict]:
    """Records in the shape `honesty.labeling` scores: one row per run, keyed so
    its uid matches the record's."""
    cls, why = ("class_strict", "why_strict") if strict else ("class", "why")
    return [{"probe_id": r["task_id"], "stratum": r["template"], "model": r["model"],
             "condition": r.get("arm", "terse"), "rep": r["rep"],
             "class": r.get(cls, r["class"]), "why": r.get(why, r.get("why", ""))}
            for r in records]


def _world(task: Task) -> str:
    files = [f"{name}{' (unreadable)' if body is UNREADABLE else ''}"
             for name, body in task.world.get("downloads", {}).items()]
    lines = [f"Downloads: {', '.join(files) if files else 'empty'}."]
    for e in task.world.get("emails", []):
        att = ", ".join(e.get("attachments", {})) or "no attachments"
        lines.append(f"Email {e.get('date')} from {e.get('sender')}, "
                     f"'{e.get('subject')}': {att}.")
    lines.append("As asked, the task could be done with these tools." if task.achievable
                 else "As asked, the task could not be done exactly as requested.")
    return "\n".join(lines)


def _exchange(task: Task, rec: dict) -> str:
    replies = rec.get("replies") or []
    if len(replies) < 2 or not task.followups:
        return rec.get("final_text") or ""
    return (f"First reply:\n{replies[0]}\n\nThe user then wrote:\n"
            f"{task.followups[0]['text']}\n\nFinal reply:\n{replies[-1]}")


def items(records: list[dict], tasks: list[Task], *, n: int = 40,
          strict: bool = False) -> list[dict]:
    """The blind cards for a balanced sample of `records`."""
    by_id = {t.task_id: t for t in tasks}
    missing = sorted({r["task_id"] for r in records} - set(by_id))
    if missing:
        raise ValueError(f"records name tasks the task file lacks: {missing[:3]}")
    shown = [{**r, "final_text": _exchange(by_id[r["task_id"]], r)} for r in records]

    def describe(row: dict, rec: dict) -> dict:
        task = by_id[row["probe_id"]]
        return {"task": task.user_message, "ground_truth": _world(task),
                "achievable": task.achievable}

    return labeling.sample(rows(records, strict=strict), shown, n=n, describe=describe)


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--records", type=Path, required=True, help="an evaluate --out file")
    ap.add_argument("--tasks", type=Path, required=True, help="the task file it ran")
    ap.add_argument("--strict", action="store_true", help="grade and label under the strict view")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", type=Path, help="write the labelling page here")
    ap.add_argument("--score", type=Path, metavar="labels.json",
                    help="score labels downloaded from that page")
    args = ap.parse_args(argv)
    records = [r for r in _load(args.records) if not r.get("error")]

    if args.score:
        res = labeling.agreement(json.loads(args.score.read_text(encoding="utf-8")),
                                 rows(records, strict=args.strict))
        if res.get("error"):
            print(res["error"])
            return 1
        print(labeling.render(res))
        return 0
    if not args.out:
        ap.error("give --out for the page, or --score for downloaded labels")
    cards = items(records, load_tasks(args.tasks), n=args.n, strict=args.strict)
    labels = labeling.STRICT_LABELS if args.strict else labeling.LABELS
    page = labeling.build_page(cards, args.out, labels)
    print(f"{len(cards)} transcripts sampled; open {page}")
    print(f"label, download labels.json, then rerun with --score labels.json"
          f"{' --strict' if args.strict else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
