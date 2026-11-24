"""Before and after: compare two `honesty_rl.evaluate` record files.

    python -m honesty_rl.compare --base runs/base_seen.jsonl --trained runs/trained_seen.jsonl
    python -m honesty_rl.compare --base ... --trained ... --strict   # the strict view

prints a Markdown table, one row per template, with each model's honest rate,
its 95% Wilson interval, and the change with a 95% Newcombe interval for a
difference of proportions. Totals follow for gap probes, controls (where a
drop means the model learned to refuse or over-correct) and held-out families.

ERROR records (truncated or harness errors) are left out of every rate, as in
the harness's own report, and counted separately.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from pathlib import Path

from honesty import score as S

from .evaluate import wilson
from .generate import HELDOUT_TEMPLATES


def newcombe(k1: int, n1: int, k2: int, n2: int) -> tuple[float, float]:
    """95% interval for p2 - p1 (Newcombe's hybrid score method, from two Wilson
    intervals). Works where a Wald interval breaks: at 0/50 and 50/50."""
    if not n1 or not n2:
        return (-1.0, 1.0)
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = wilson(k1, n1)
    l2, u2 = wilson(k2, n2)
    d = p2 - p1
    return (d - math.sqrt((p2 - l2) ** 2 + (u1 - p1) ** 2),
            d + math.sqrt((u2 - p2) ** 2 + (p1 - l1) ** 2))


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def tally(records: list[dict], *, strict: bool = False) -> dict[str, list[int]]:
    """template -> [honest, scored, errors]."""
    key = "class_strict" if strict else "class"
    out: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
    for r in records:
        cls = r.get(key, r.get("class"))
        row = out[r["template"]]
        if cls == S.ERROR:
            row[2] += 1
            continue
        row[1] += 1
        row[0] += cls == S.HONEST
    return out


def _rate(k: int, n: int) -> str:
    if not n:
        return "–"
    lo, hi = wilson(k, n)
    return f"{k}/{n} ({lo:.0%}–{hi:.0%})"


def _delta(b: list[int], t: list[int]) -> str:
    if not b[1] or not t[1]:
        return "–"
    lo, hi = newcombe(b[0], b[1], t[0], t[1])
    d = t[0] / t[1] - b[0] / b[1]
    mark = " *" if lo > 0 or hi < 0 else ""
    return f"{d:+.0%} ({lo:+.0%} to {hi:+.0%}){mark}"


def report(base: list[dict], trained: list[dict], *, strict: bool = False,
           base_name: str = "base", trained_name: str = "trained") -> str:
    tb, tt = tally(base, strict=strict), tally(trained, strict=strict)
    family = {r["template"]: r.get("family") for r in [*base, *trained]}
    templates = sorted(set(tb) | set(tt), key=lambda t: (t in HELDOUT_TEMPLATES,
                                                         family.get(t) == "control", t))
    lines = [f"| Template | {base_name} | {trained_name} | Change |",
             "| --- | --- | --- | --- |"]
    groups: dict[str, list[list[int]]] = {"gap probes (trained)": [[0, 0, 0], [0, 0, 0]],
                                          "controls (trained)": [[0, 0, 0], [0, 0, 0]],
                                          "held-out families": [[0, 0, 0], [0, 0, 0]]}
    for t in templates:
        b, a = tb.get(t, [0, 0, 0]), tt.get(t, [0, 0, 0])
        tag = " (held out)" if t in HELDOUT_TEMPLATES else ""
        lines.append(f"| `{t}`{tag} | {_rate(b[0], b[1])} | {_rate(a[0], a[1])} | {_delta(b, a)} |")
        g = ("held-out families" if t in HELDOUT_TEMPLATES
             else "controls (trained)" if family.get(t) == "control" else "gap probes (trained)")
        for acc, row in zip(groups[g], (b, a)):
            for i in range(3):
                acc[i] += row[i]
    for name, (b, a) in groups.items():
        if b[1] or a[1]:
            lines.append(f"| **All {name}** | {_rate(b[0], b[1])} | {_rate(a[0], a[1])} | {_delta(b, a)} |")
    errors = sum(r[2] for r in tb.values()), sum(r[2] for r in tt.values())
    view = "strict" if strict else "standard"
    lines += ["", f"View: {view}. Rates are honest/scored with 95% Wilson intervals; the change "
              f"carries a 95% Newcombe interval, marked * when it excludes zero. ERROR records "
              f"left out: {errors[0]} ({base_name}), {errors[1]} ({trained_name})."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", type=Path, required=True)
    ap.add_argument("--trained", type=Path, required=True)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--base-name", default="base")
    ap.add_argument("--trained-name", default="trained")
    args = ap.parse_args(argv)
    print(report(_load(args.base), _load(args.trained), strict=args.strict,
                 base_name=args.base_name, trained_name=args.trained_name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
