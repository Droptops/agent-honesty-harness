"""Reword training prompts with a language model, keeping every fact verbatim.

Template wording repeats: a policy can learn the phrasing instead of the task.
`paraphrase_tasks` asks a model (any OpenAI-compatible endpoint; OpenRouter in
practice) to restate each prompt as another person would, then accepts the
rewrite only if `check` passes:

  * every file name, email address, quoted string and number in the original
    appears verbatim, and the rewrite introduces none of its own;
  * an instruction not to send survives wherever the original has one;
  * mentioning email (the "check my email" hint h01 and c04 randomize) stays
    exactly as present or absent as in the original;
  * no hint word the original lacks appears ("date", "current", "verify"...),
    so a rewrite cannot leak the answer to the probe;
  * the length stays within half to double the original.

A rejected rewrite keeps the template wording. Facts, worlds and graders are
untouched: graders read `facts`, never the prompt, so a reworded task grades
exactly as its original. Evaluation sets are left on template wording so the
published baselines stay comparable.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from .spec import Task

_FILE = re.compile(r"\b[\w.-]+\.(?:xlsx|csv|pdf|docx|txt|json|zip)\b", re.I)
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_QUOTED = re.compile(r"(?<!\w)'([^']{2,80})'(?!\w)")  # a quoted subject, not a contraction
_NUMBER = re.compile(r"\b\d+\b")
_NO_SEND = re.compile(r"\b(?:do not|don'?t|never)\s+(?:actually\s+)?send\b|\bjust a draft\b|"
                      r"\bleave it as a draft\b|\bdraft it\b", re.I)
_EMAIL_WORD = re.compile(r"\b(?:e-?mail|inbox|mailbox)\b", re.I)
_HINTS = re.compile(r"\b(?:date[ds]?|current(?:ly)?|latest|old(?:er)?|stale|verify|check whether|"
                    r"honest(?:ly)?|careful(?:ly)?|outdated|previous|last year|versions?|template)\b", re.I)

INSTRUCTION = (
    "Rewrite the user's request below as a different person might phrase it to their assistant. "
    "Keep every file name, email address, quoted text and number exactly as written. Keep every "
    "instruction, including any instruction not to send something. Do not add facts, hints, "
    "warnings or new instructions, and do not answer the request. Reply with the rewritten "
    "request only."
)


def _facts(text: str) -> set[str]:
    quoted = {m.group(1) for m in _QUOTED.finditer(text)}
    return (set(_FILE.findall(text)) | set(_EMAIL.findall(text)) | quoted
            | set(_NUMBER.findall(text)))


def check(original: str, rewrite: str, allowed_files: frozenset[str] = frozenset()) -> str | None:
    """None if the rewrite keeps the request intact, else the reason it fails.
    `allowed_files` may appear though the original does not name them (files that
    exist in the task's world, such as step2.txt when the prompt says "through")."""
    r = rewrite.strip()
    if not r:
        return "empty"
    if not 0.5 * len(original) <= len(r) <= 2.0 * len(original):
        return "length"
    want = _facts(original)
    missing = sorted(f for f in want if f not in r)
    if missing:
        return f"dropped {missing[:3]}"
    extra = sorted(f for f in (set(_FILE.findall(r)) | set(_EMAIL.findall(r)) | set(_NUMBER.findall(r)))
                   if f not in original and f not in allowed_files)
    if extra:
        return f"added {extra[:3]}"
    if _NO_SEND.search(original) and not _NO_SEND.search(r):
        return "lost the instruction not to send"
    if bool(_EMAIL_WORD.search(original)) != bool(_EMAIL_WORD.search(r)):
        return "changed whether email is mentioned"
    leaked = sorted({h.lower() for h in _HINTS.findall(r)} - {h.lower() for h in _HINTS.findall(original)})
    if leaked:
        return f"added hint words {leaked}"
    return None


def openai_rewriter(model: str, temperature: float = 0.9) -> Callable[[str], str]:
    """A rewrite function backed by an OpenAI-compatible endpoint (OPENAI_BASE_URL)."""
    from openai import OpenAI  # optional dependency: the `run` extra

    client = OpenAI(max_retries=4, timeout=120.0)

    def rewrite(prompt: str) -> str:
        r = client.chat.completions.create(
            model=model, temperature=temperature,
            messages=[{"role": "system", "content": INSTRUCTION},
                      {"role": "user", "content": prompt}])
        return (r.choices[0].message.content or "").strip()

    return rewrite


def paraphrase_tasks(tasks: list[Task], rewrite: Callable[[str], str], *,
                     concurrency: int = 8) -> tuple[list[Task], dict[str, int]]:
    """Reword each task's prompt; return the tasks (rewritten where `check`
    accepted the rewrite) and a tally of outcomes by reason."""
    def one(t: Task) -> tuple[Task, str]:
        try:
            new = rewrite(t.prompt)
        except Exception as exc:  # an endpoint failure keeps the template wording
            return t, f"error: {type(exc).__name__}"
        world = t.world.get("downloads", {})
        files = frozenset(world) | frozenset(a for e in t.world.get("emails", []) for a in e.get("attachments", {}))
        why = check(t.prompt, new, files)
        if why is not None:
            return t, why.split(" [")[0]
        return dataclasses.replace(t, prompt=new.strip(),
                                   facts={**t.facts, "paraphrased": True}), "accepted"

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(pool.map(one, tasks))
    tally: dict[str, int] = {}
    for _, why in results:
        tally[why] = tally.get(why, 0) + 1
    return [t for t, _ in results], tally
