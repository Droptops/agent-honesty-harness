"""One entry point.

    python -m honesty selftest              # no API: scorer oracles + fixtures
    python -m honesty baselines             # no API: null strategies
    python -m honesty run --reps 5          # the sweep
    python -m honesty run --arm loud        # the tool-description ablation
    python -m honesty report                # score + RESULTS.md
    python -m honesty all --reps 5          # everything, in order

Every command is resumable and idempotent: `run` skips cells already in the
JSONL, and `report` recomputes from raw records, so scoring changes never
require re-running the API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# The reports contain ≤, ×, — and box-drawing punctuation. A Windows console
# defaults to cp1252 and raises on all of them, which crashed `report` *after*
# it had already written a correct RESULTS.md -- so the command exited non-zero
# with a good file on disk, which is the worst of both worlds.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent.parent
RESULTS = HERE / "results"
RAW = RESULTS / "records.jsonl"

DEFAULT_MODELS = ["claude-opus-5", "claude-sonnet-5"]


def _hydrate_keys() -> None:
    """On Windows a User-scope variable set after this process started is
    invisible to it. Pull the two keys in from the registry if the environment
    is missing them. Values are never printed, logged, or written."""
    if os.name != "nt":
        return
    try:
        import winreg
    except ImportError:
        return
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "OPENAI_PROJECT"):
        if os.environ.get(var):
            continue
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                val, _ = winreg.QueryValueEx(k, var)
            if val:
                os.environ[var] = val
        except OSError:
            pass


def cmd_selftest(args) -> int:
    from . import baselines
    from .score import score_records

    rows = score_records(baselines.records())
    problems = baselines.check(rows)
    print("=== scorer oracles ===")
    for name in ("ideal_honest", "sneaky_substituter"):
        sel = [r for r in rows if r["model"] == name]
        from collections import Counter
        print(f"  {name:20s} {dict(Counter(r['class'] for r in sel))}")
    if problems:
        print("\nFAILURES:")
        for p in problems:
            print("  " + p)
        return 1
    print("\n  ideal_honest is never accused; sneaky_substituter is always caught.")

    import subprocess
    print("\n=== claim fixtures ===")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", str(HERE / "tests")],
                       cwd=HERE)
    return r.returncode


def cmd_baselines(args) -> int:
    from collections import Counter

    from . import baselines
    from .score import DISHONEST, HONEST, OVER_REFUSED, SCORED, score_records

    rows = score_records(baselines.records())
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "baselines.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")

    print("=== NULL BASELINES (no API calls) ===")
    for name in ("always_refuse", "always_claim_done", "ideal_honest",
                 "sneaky_substituter"):
        c = Counter(r["class"] for r in rows if r["model"] == name)
        n = sum(c[k] for k in SCORED)
        rest = "  ".join(f"{k}={v}" for k, v in sorted(c.items()) if k != HONEST)
        print(f"  {name:20s} honest {c[HONEST]}/{n}   {rest}")
    print("\n  A real model must beat always_refuse and always_claim_done on")
    print("  both halves (gaps and controls) to be measuring anything at all.")

    problems = baselines.check(rows)
    if problems:
        print("\n  SCORER PROBLEMS:")
        for p in problems:
            print("   " + p)
        return 1
    return 0


def cmd_run(args) -> int:
    _hydrate_keys()
    from . import probes as P
    from . import runner

    models = args.models or DEFAULT_MODELS
    selected = P.select(ids=args.probes, families=args.families)
    arms = tuple(args.arm)
    started = time.strftime("%Y-%m-%d %H:%M:%S")

    print(f"models={models}  probes={len(selected)}  reps={args.reps}  arms={arms}")
    print(f"→ {len(models)*len(selected)*args.reps*len(arms)} runs max\n")

    records = runner.run_sweep(
        models, selected, args.reps, RAW,
        arms=arms, concurrency=args.concurrency, max_tokens=args.max_tokens,
        effort=args.effort, system=args.system, resume=not args.fresh,
    )
    cost = sum(r.get("cost_usd") or 0 for r in records)
    unpriced = sorted({r["model"] for r in records if r.get("cost_usd") is None
                       and not r.get("error")})
    # Describe the CORPUS, not this invocation. A second `run` (the ablation
    # arm) used to overwrite the meta with its own narrower arguments, leaving
    # a file that misdescribed the records sitting next to it.
    import collections as _c
    runner.write_meta(RESULTS / "run_meta.json", {
        "schema": runner.SCHEMA_VERSION, "started": started, "models": models,
        "probes": sorted({r["task_id"] for r in records}),
        "reps": args.reps,
        "arms": sorted({r.get("arm", "terse") for r in records}),
        "records_per_arm": dict(_c.Counter(r.get("arm", "terse") for r in records)),
        "max_tokens": args.max_tokens, "effort": args.effort,
        "system_prompt": args.system, "records": len(records),
        "cost_usd": round(cost, 4),
        "unpriced_models": unpriced,
        "unpriced_tokens": {
            m: {"input": sum(r.get("usage", {}).get("input_tokens", 0)
                             for r in records if r["model"] == m),
                "output": sum(r.get("usage", {}).get("output_tokens", 0)
                              for r in records if r["model"] == m)}
            for m in unpriced
        },
        "note": "temperature is not settable on these models; per-cell variance "
                "is sampling variance and is what reps measure. cost_usd covers "
                "only models with rates in providers.PRICES -- see "
                "unpriced_tokens for the rest.",
    })
    tail = (f"  (+{', '.join(unpriced)}: tokens recorded, rates not in the table)"
            if unpriced else "")
    print(f"\n{len(records)} records in {RAW}  ·  ${cost:.2f}{tail}")
    return 0


def cmd_report(args) -> int:
    from . import baselines
    from . import report as R
    from . import runner
    from .score import score_records

    records = runner.load_jsonl(RAW)
    if not records:
        print(f"no records at {RAW} — run `python -m honesty run` first")
        return 1
    rows = score_records(records)
    strict_rows = score_records(records, strict=True)
    base = score_records(baselines.records())
    meta = {}
    mp = RESULTS / "run_meta.json"
    if mp.exists():
        meta = json.loads(mp.read_text(encoding="utf-8"))
    jp = RESULTS / "judge.json"
    judge = json.loads(jp.read_text(encoding="utf-8")) if jp.exists() else None
    path = R.write(rows, RESULTS, baselines=base, meta=meta, judge=judge,
                   strict_rows=strict_rows)
    print(R.markdown(rows, baselines=base, meta=meta, judge=judge,
                     strict_rows=strict_rows))
    print(f"\nwritten: {path}")
    return 0


def cmd_judge(args) -> int:
    _hydrate_keys()
    from . import judge
    from . import runner
    from .score import score_records

    records = runner.load_jsonl(RAW)
    rows = score_records(records)
    out = judge.adjudicate(rows, records, mode=args.mode, limit=args.limit)
    (RESULTS / "judge.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(judge.render(out))
    return 0


def cmd_label(args) -> int:
    from . import labeling, runner
    from .score import score_records

    records = runner.load_jsonl(RAW)
    if not records:
        print(f"no records at {RAW}")
        return 1
    rows = score_records(records)

    if args.score:
        src = Path(args.score)
        if not src.exists():
            print(f"no such file: {src}\n"
                  f"  the Download button on results/labeling.html saves it as "
                  f"labels.json, usually in your Downloads folder.")
            return 1
        labels = json.loads(src.read_text(encoding="utf-8"))
        res = labeling.agreement(labels, rows)
        if res.get("error"):
            print(res["error"])
            return 1
        k = res["cohens_kappa"]
        print(f"=== HUMAN vs MECHANICAL ({res['n']} labelled) ===")
        print(f"  raw agreement : {100*res['raw_agreement']:.1f}%  "
              f"(meaningless alone on a skewed corpus)")
        if res["kappa_valid"]:
            print(f"  Cohen's kappa : {k:.3f}  — {labeling.interpret(k)}")
        else:
            print(f"  Cohen's kappa : UNDEFINED — {res['kappa_note']}")

        # On a machine-constant corpus this is the whole result.
        missed = res["detector_missed"]
        print(f"\n  you called {res['human_non_honest']} row(s) not-honest; "
              f"the detector missed {len(missed)} of them")
        if missed:
            print("  MEASURED FALSE NEGATIVES — the direction regex cannot self-detect:")
            for d in missed:
                print(f"    {d['uid']}\n      you={d['human']}  detector=HONEST "
                      f"({d['machine_why']})")
        if res["detector_overcalled"]:
            print(f"\n  {len(res['detector_overcalled'])} row(s) the detector accused "
                  f"and you did not — false positives, the more damaging direction:")
            for d in res["detector_overcalled"]:
                print(f"    {d['uid']}  detector={d['machine']} ({d['machine_why']})")
        if not res["disagreements"]:
            print("  no disagreements at all — report that as the n it is, not as "
                  "validation; 50 rows of a saturated corpus is a weak test.")
        print("\n  per class (human / machine / agreed):")
        for cls, d in res["per_class"].items():
            print(f"    {cls:14s} {d['human']:3d} / {d['machine']:3d} / {d['agreed']:3d}")
        (RESULTS / "human_agreement.json").write_text(
            json.dumps(res, indent=2), encoding="utf-8")
        print(f"\n  written: {RESULTS / 'human_agreement.json'}")
        return 0

    items = labeling.sample(rows, records, n=args.n)
    page = labeling.build_page(items, RESULTS / "labeling.html")
    counts = {}
    for it in items:
        counts[it["uid"].split("|")[0]] = counts.get(it["uid"].split("|")[0], 0) + 1
    print(f"{len(items)} transcripts sampled across {len(counts)} probes")
    print(f"open: {page}")
    print("\nThe page never shows the mechanical verdict — that is the point. "
          "Label, download labels.json, then:")
    print(f"  python -m honesty label --score labels.json")
    return 0


def cmd_all(args) -> int:
    for fn in (cmd_selftest, cmd_baselines):
        rc = fn(args)
        if rc:
            print("\nstopping: fix the scorer before spending API calls.")
            return rc
        print()
    rc = cmd_run(args)
    if rc:
        return rc
    print()
    return cmd_report(args)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="honesty", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_run_args(p):
        p.add_argument("--models", nargs="+", default=None,
                       help=f"default: {' '.join(DEFAULT_MODELS)}. "
                            "Prefix with 'openai:' to route to OpenAI.")
        p.add_argument("--reps", type=int, default=5,
                       help="repetitions per cell (default 5; n=1 has misled "
                            "every measurement in this project)")
        p.add_argument("--probes", nargs="+", default=None)
        p.add_argument("--families", nargs="+", default=None,
                       choices=["easy_gap", "hard_gap", "control"])
        p.add_argument("--arm", nargs="+", default=["terse"],
                       choices=["terse", "loud", "artifact"])
        p.add_argument("--concurrency", type=int, default=6)
        p.add_argument("--max-tokens", dest="max_tokens", type=int, default=8000,
                       help="must cover thinking as well as the reply")
        p.add_argument("--effort", default=None,
                       choices=["low", "medium", "high", "xhigh", "max"])
        p.add_argument("--system", default=None, help="optional system prompt")
        p.add_argument("--fresh", action="store_true",
                       help="discard existing records instead of resuming")

    sub.add_parser("selftest").set_defaults(func=cmd_selftest)
    sub.add_parser("baselines").set_defaults(func=cmd_baselines)
    r = sub.add_parser("run"); add_run_args(r); r.set_defaults(func=cmd_run)
    sub.add_parser("report").set_defaults(func=cmd_report)
    a = sub.add_parser("all"); add_run_args(a); a.set_defaults(func=cmd_all)
    lb = sub.add_parser("label", help="blind human labelling + Cohen's kappa")
    lb.add_argument("--n", type=int, default=50)
    lb.add_argument("--score", default=None, metavar="labels.json",
                    help="score a downloaded labels.json against the scorer")
    lb.set_defaults(func=cmd_label)

    j = sub.add_parser("judge")
    j.add_argument("--mode", default="dual", choices=["anthropic", "openai", "dual"])
    j.add_argument("--limit", type=int, default=40)
    j.set_defaults(func=cmd_judge)

    args = ap.parse_args(argv)
    return args.func(args)
