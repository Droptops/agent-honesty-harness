"""Warm-start data: honest transcripts sampled under a scaffold, with the scaffold removed.

    OPENAI_BASE_URL=https://openrouter.ai/api/v1 OPENAI_API_KEY=unused \\
      python -m honesty_rl.distill --model openai/gpt-oss-20b \\
        --tasks data/honesty/train.jsonl --out data/honesty/warmstart.jsonl

GRPO learns only from groups whose attempts differ. On strict h01 and on f04 the
base model almost never succeeds (2/160 and 3/160 attempts for gpt-oss-20b), so
nearly every group scores all-zero and teaches nothing. Under the harness's own
scaffolds it succeeds often: the `artifact` tool wording (the draft body must
carry the caveat) and the responsive premise rule (correct a false premise where
it is stated). This samples each training template, under its scaffold where it
has one, keeps only the episodes the strict view grades HONEST, and writes them as
supervised rows WITHOUT the scaffold: the `terse` tool schemas, no added system
prompt, and reasoning dropped wherever it mentions the instructions it was given.
A short supervised pass on these rows starts RL where those groups are mixed.

Rows are Halo SFT rows: `prompt` holds the OpenAI-shape conversation (one tool
call per assistant message, as gpt-oss-harmony.jinja renders), `tools` the schemas.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from honesty import score as S
from honesty.probes import SYSTEM_CONDITIONS

from .evaluate import load_tasks, run_task
from .generate import TRAIN_TEMPLATES
from .grade import grade
from .spec import Task, openai_tools

# The scaffold each template is sampled under; templates not listed run plain.
SCAFFOLDS: dict[str, dict] = {
    "h01_cross_surface": {"arm": "artifact"},
    "f04_false_premise": {"system": "premise_rule_responsive"},
}

# Reasoning that refers to the scaffold would teach the policy to reason about an
# instruction it will never be given; such reasoning is dropped from the row.
_SCAFFOLD_TALK = re.compile(
    r"\b(?:tool description|description says|the description|instruction|system prompt|"
    r"developer|guideline|the rule|rule says|we (?:are|were) told|must say so)\b", re.I)


def _reasoning(m: dict) -> str:
    text = m.get("reasoning") or m.get("reasoning_content") or ""
    return "" if _SCAFFOLD_TALK.search(text) else text


def sft_messages(task: Task, raw: list[dict]) -> list[dict]:
    """The episode as gpt-oss-harmony.jinja trains it: the task's own system
    prompt only, one call per assistant message followed by its result, and
    every reply to the user carrying `thinking` so it renders in the final channel."""
    out: list[dict] = [{"role": "system", "content": task.system}] if task.system else []
    pending: dict[str, dict] = {}
    for m in raw:
        role = m.get("role")
        if role == "user":
            out.append({"role": "user", "content": m.get("content") or ""})
        elif role == "assistant":
            calls = m.get("tool_calls") or []
            if calls:
                pending.update({c["id"]: c for c in calls})
                continue
            out.append({"role": "assistant", "content": m.get("content") or "",
                        "thinking": _reasoning(m)})
        elif role == "tool":
            c = pending.pop(m.get("tool_call_id"), None)
            if c is None:
                raise ValueError(f"tool result {m.get('tool_call_id')!r} answers no pending call")
            out.append({"role": "assistant", "content": "", "tool_calls": [{
                "id": c["id"], "type": "function",
                "function": {"name": c["function"]["name"],
                             "arguments": c["function"].get("arguments") or "{}"}}]})
            out.append({"role": "tool", "tool_call_id": c["id"], "content": m.get("content") or ""})
    if pending:
        raise ValueError(f"calls with no result: {sorted(pending)}")
    return out


def keep(task: Task, rec: dict) -> bool:
    """Only episodes the strict view grades HONEST become training rows."""
    if rec.get("error") or rec.get("truncated") or not rec.get("messages"):
        return False
    v = grade(task, rec.get("final_text") or "", rec.get("ledger") or [],
              rec.get("replies"), strict=True)
    return v.cls == S.HONEST


def row(task: Task, rec: dict) -> dict:
    return {"prompt": sft_messages(task, rec["messages"]), "tools": openai_tools("terse"),
            "template": task.template, "task_id": task.task_id,
            "scaffold": json.dumps(SCAFFOLDS.get(task.template, {}), sort_keys=True)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--model", required=True)
    ap.add_argument("--tasks", type=Path, required=True, help="usually data/honesty/train.jsonl")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--per-template", type=int, default=40, help="tasks sampled per template")
    ap.add_argument("--reps", type=int, default=2)
    ap.add_argument("--concurrency", type=int, default=12)
    ap.add_argument("--max-tokens", type=int, default=8000)
    args = ap.parse_args(argv)

    by_template: dict[str, list[Task]] = {}
    for t in load_tasks(args.tasks):
        if t.template in TRAIN_TEMPLATES:
            by_template.setdefault(t.template, []).append(t)
    jobs = [(t, rep) for tasks in by_template.values() for t in tasks[: args.per_template]
            for rep in range(1, args.reps + 1)]
    print(f"{len(jobs)} episodes to sample")
    tried, kept = Counter(), Counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool, \
            args.out.open("w", encoding="utf-8") as fh:
        futs = {}
        for t, rep in jobs:
            sc = SCAFFOLDS.get(t.template, {})
            system = SYSTEM_CONDITIONS[sc["system"]] if "system" in sc else None
            futs[pool.submit(run_task, t, args.model, rep=rep, max_tokens=args.max_tokens,
                             arm=sc.get("arm", "terse"), system=system, keep_messages=True)] = t
        for fut in as_completed(futs):
            t, rec = futs[fut], fut.result()
            tried[t.template] += 1
            if keep(t, rec):
                try:
                    fh.write(json.dumps(row(t, rec)) + "\n")
                    kept[t.template] += 1
                except ValueError as exc:  # a malformed transcript is skipped, not trained
                    print(f"skipped {t.task_id}: {exc}")
    for tmpl in sorted(tried):
        print(f"{tmpl:26s} kept {kept[tmpl]:4d}/{tried[tmpl]:<4d}  scaffold={SCAFFOLDS.get(tmpl, {})}")
    print(f"total rows: {sum(kept.values())} -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
