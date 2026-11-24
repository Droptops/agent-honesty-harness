"""Write the training and evaluation datasets.

    python -m honesty_rl.generate --out data/honesty

writes four JSONL files, one task per line (`prompt`, `task`, `template`,
`family`, `split`):

  train.jsonl          variants of the TRAIN templates
  eval_seen.jsonl      fresh variants of the TRAIN templates (unseen instances)
  eval_heldout.jsonl   variants of the HELDOUT templates (probe families the
                       model never trains on)
  canonical.jsonl      the original probes, exactly as published

f04 and c09 carry a scripted second user turn in each task's `followups`; an
environment plays it after the agent's first reply (Episode.on_reply).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from .spec import Task
from .variants import ALL_TEMPLATES, canonical, generate

TRAIN_TEMPLATES = ("e01_missing_file", "e02_no_send_tool", "e03_wrong_version",
                   "e04_unreadable", "h01_cross_surface", "h03_long_horizon",
                   "c01_read", "c02_draft", "c03_multistep", "c04_legit_attachment",
                   "f04_false_premise", "c09_true_premise")
HELDOUT_TEMPLATES = ("h02_stale_data", "h04_partial_success",
                     "p07_template_substitute", "c07_contract_readable")
assert set(TRAIN_TEMPLATES) | set(HELDOUT_TEMPLATES) == set(ALL_TEMPLATES)
assert not set(TRAIN_TEMPLATES) & set(HELDOUT_TEMPLATES)

# h01 is the probe that separates models in the published sweep; c04 is its
# mirror, weighted the same so that refusing every email attachment never pays.
DEFAULT_WEIGHTS = {"h01_cross_surface": 2.0, "c04_legit_attachment": 2.0}


def _fingerprint(task: Task) -> str:
    """Identity of a task's content, ignoring its id."""
    d = task.to_dict()
    d.pop("task_id")
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()


def _unique(tasks: list[Task], seen: set[str]) -> list[Task]:
    out = []
    for t in tasks:
        fp = _fingerprint(t)
        if fp not in seen:
            seen.add(fp)
            out.append(t)
    return out


def build(per_template: int, eval_per_template: int, seed: int,
          weights: dict[str, float] | None = None) -> dict[str, list[Task]]:
    weights = {**DEFAULT_WEIGHTS, **(weights or {})}
    seen: set[str] = set()
    # Eval sets are drawn first, so a template with few distinct instances
    # still gets its full eval share and training never sees those instances.
    eval_seen: list[Task] = []
    for t in TRAIN_TEMPLATES:
        eval_seen += _unique(generate(t, eval_per_template * 3, seed=seed + 1,
                                      start=10**5), seen)[:eval_per_template]
    train: list[Task] = []
    for t in TRAIN_TEMPLATES:
        n = round(per_template * weights.get(t, 1.0))
        # Oversample and dedupe: templates with few distinct instances repeat.
        train += _unique(generate(t, n * 3, seed=seed), seen)[:n]
    eval_heldout: list[Task] = []
    for t in HELDOUT_TEMPLATES:
        eval_heldout += _unique(generate(t, eval_per_template * 3, seed=seed + 2,
                                         start=2 * 10**5), seen)[:eval_per_template]
    random.Random(seed).shuffle(train)
    return {"train": train, "eval_seen": eval_seen, "eval_heldout": eval_heldout,
            "canonical": [canonical(t) for t in ALL_TEMPLATES]}


def write(splits: dict[str, list[Task]], out: Path) -> dict[str, Counter]:
    out.mkdir(parents=True, exist_ok=True)
    counts = {}
    for name, tasks in splits.items():
        with (out / f"{name}.jsonl").open("w", encoding="utf-8") as fh:
            for t in tasks:
                fh.write(json.dumps(t.to_row(split=name)) + "\n")
        counts[name] = Counter(t.template for t in tasks)
    return counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=Path("data/honesty"))
    ap.add_argument("--per-template", type=int, default=300,
                    help="training variants per template, before weights")
    ap.add_argument("--eval-per-template", type=int, default=50)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--weight", action="append", default=[], metavar="TEMPLATE=W",
                    help="override a template's training weight (repeatable)")
    args = ap.parse_args(argv)
    weights = {k: float(v) for k, v in (w.split("=", 1) for w in args.weight)}
    counts = write(build(args.per_template, args.eval_per_template, args.seed, weights),
                   args.out)
    for name, c in counts.items():
        print(f"{name:13s} {sum(c.values()):5d}  " +
              "  ".join(f"{k.split('_')[0]}={v}" for k, v in sorted(c.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
