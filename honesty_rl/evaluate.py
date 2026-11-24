"""Run a model on a generated task file and report its honest rate per template.

    OPENAI_BASE_URL=http://localhost:8000/v1 OPENAI_API_KEY=unused \\
      python -m honesty_rl.evaluate --model openai/gpt-oss-20b \\
        --tasks data/honesty/eval_heldout.jsonl --out runs/base_heldout.jsonl

Any OpenAI-compatible endpoint works: a vLLM server during training, or
OpenRouter for a baseline before any GPU is available. The agent loop is the
harness's own (`honesty.providers.OpenAIAgent`), with the same tools, prefix and
turn limit, so a canonical task here is the same experiment as `python -m
honesty run`. Records are appended as they finish; rerunning resumes.
"""

from __future__ import annotations

import argparse
import json
import math
import time
import traceback
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from honesty import score as S

from .grade import grade, objective
from .spec import Episode, Task, tools


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def run_task(task: Task, model: str, *, rep: int = 1, max_tokens: int = 8000,
             agent_factory=None) -> dict:
    """One task, one model, one repetition. Never raises."""
    from honesty import providers

    started = time.time()
    rec: dict = {"model": model, "task_id": task.task_id, "template": task.template,
                 "family": task.family, "achievable": task.achievable, "rep": rep}
    try:
        make = agent_factory or (lambda: providers.OpenAIAgent(
            model, tools("terse"), max_tokens=max_tokens, system=task.system))
        agent = make()
        with Episode(task) as ep:
            agent.user(task.user_message)
            text, turns, truncated, stop = "", 0, False, ""
            while turns < task.max_turns:
                turns += 1
                turn = agent.step()
                stop = turn.stop_reason
                if stop in ("max_tokens", "length"):
                    truncated, text = True, turn.text
                    break
                if turn.tool_calls:
                    agent.results([{"id": c["id"], "content": ep.call(c["name"], c["input"])}
                                   for c in turn.tool_calls])
                    continue
                text = turn.text
                break
            else:
                truncated, stop = True, "max_turns"
            v = grade(task, text, ep.ledger, truncated=truncated)
            vs = grade(task, text, ep.ledger, truncated=truncated, strict=True)
            rec.update(turns=turns, stop_reason=stop, truncated=truncated,
                       final_text=text, ledger=ep.ledger, usage=getattr(agent, "usage", None))
    except Exception as exc:
        v = vs = S.Verdict(S.ERROR, f"{type(exc).__name__}: {exc}")
        rec.update(error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc()[-1200:])
    rec.update(**_verdict_fields(v, vs), elapsed_s=round(time.time() - started, 2))
    return rec


def _verdict_fields(v: S.Verdict, vs: S.Verdict) -> dict:
    """Both views on every record, so either can be summarised without a rerun."""
    return {"class": v.cls, "why": v.why, "flags": v.flags or {}, "reward": objective(v),
            "class_strict": vs.cls, "why_strict": vs.why, "reward_strict": objective(vs)}


def regrade(records: list[dict], tasks: dict[str, Task]) -> list[dict]:
    """Re-score saved transcripts with the current graders; no model calls."""
    out = []
    for r in records:
        t = tasks.get(r["task_id"])
        if t is not None and not r.get("error"):
            kw = {"truncated": bool(r.get("truncated"))}
            r = {**r, **_verdict_fields(grade(t, r.get("final_text") or "", r.get("ledger") or [], **kw),
                                        grade(t, r.get("final_text") or "", r.get("ledger") or [],
                                              strict=True, **kw))}
        out.append(r)
    return out


def load_tasks(path: Path) -> list[Task]:
    return [Task.from_json(json.loads(line)["task"])
            for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def summarise(records: list[dict], *, strict: bool = False) -> str:
    key = "class_strict" if strict else "class"
    by = defaultdict(Counter)
    for r in records:
        by[r["template"]][r.get(key, r["class"])] += 1
    lines = [f"{'template':26s} {'honest':>9s} {'95% CI':>13s}  classes"]
    tot_k = tot_n = 0
    for t in sorted(by):
        c = by[t]
        n = sum(v for k, v in c.items() if k != S.ERROR)
        k = c[S.HONEST]
        tot_k, tot_n = tot_k + k, tot_n + n
        lo, hi = wilson(k, n)
        rest = " ".join(f"{cls}={v}" for cls, v in sorted(c.items()) if cls != S.HONEST)
        lines.append(f"{t:26s} {k:4d}/{n:<4d} {lo:6.0%}-{hi:<6.0%}  {rest}")
    lo, hi = wilson(tot_k, tot_n)
    lines.append(f"{'ALL':26s} {tot_k:4d}/{tot_n:<4d} {lo:6.0%}-{hi:<6.0%}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True, help="model id at the OpenAI-compatible endpoint")
    ap.add_argument("--tasks", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--reps", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="first N tasks only")
    ap.add_argument("--templates", nargs="*", default=None)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--max-tokens", type=int, default=8000)
    ap.add_argument("--strict", action="store_true",
                    help="summarise the strict view (the h01 draft must carry the caveat)")
    ap.add_argument("--regrade", action="store_true",
                    help="re-score the records already in --out with the current graders; no model calls")
    args = ap.parse_args(argv)

    tasks = load_tasks(args.tasks)
    if args.templates:
        tasks = [t for t in tasks if t.template in set(args.templates)]
    tasks = tasks[: args.limit] if args.limit else tasks
    if args.regrade:
        records = regrade([json.loads(line) for line in args.out.read_text(encoding="utf-8").splitlines()
                           if line.strip()], {t.task_id: t for t in tasks})
        args.out.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
        print(summarise([r for r in records if r["task_id"] in {t.task_id for t in tasks}],
                        strict=args.strict))
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if args.out.exists():
        for line in args.out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if not r.get("error"):
                done.add((r["task_id"], r["rep"]))
    jobs = [(t, rep) for t in tasks for rep in range(1, args.reps + 1)
            if (t.task_id, rep) not in done]
    print(f"{len(jobs)} runs to go ({len(done)} done)")
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futs = [pool.submit(run_task, t, args.model, rep=rep, max_tokens=args.max_tokens)
                for t, rep in jobs]
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            with args.out.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec) + "\n")
            print(f"[{i}/{len(jobs)}] {rec['task_id']:32s} {rec['class']}")
    records = [json.loads(line) for line in args.out.read_text(encoding="utf-8").splitlines()]
    print(summarise([r for r in records if r["task_id"] in {t.task_id for t in tasks}],
                    strict=args.strict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
