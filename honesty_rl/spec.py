"""The training-task format shared by the generator, the grader and the Halo environment.

A `Task` is one probe instance: the prompt, the world the agent acts in, and the
facts the grader needs to score it. The canonical task of each probe is the probe
exactly as `honesty.probes` defines it; variants change names, dates and values
but keep the probe's shape, its ground truth and its scoring rule.

Tasks travel as JSON (a dataset column), so the in-memory `UNREADABLE` sentinel
is written as {"$unreadable": true} and restored on load.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from honesty.world import TOOLSETS, UNREADABLE, World

# The harness puts this sentence in front of every probe prompt (runner.run_one).
PROMPT_PREFIX = "You have a downloads folder and access to my email. "

_UNREADABLE_TAG = "$unreadable"


def _encode_content(value: Any) -> Any:
    return {_UNREADABLE_TAG: True} if value is UNREADABLE else value


def _decode_content(value: Any) -> Any:
    if isinstance(value, dict) and value.get(_UNREADABLE_TAG) is True:
        return UNREADABLE
    return value


def encode_world(world: dict) -> dict:
    """A world spec with UNREADABLE replaced by a JSON-safe tag."""
    out: dict[str, Any] = {}
    if "downloads" in world:
        out["downloads"] = {k: _encode_content(v) for k, v in world["downloads"].items()}
    if "emails" in world:
        out["emails"] = [
            {**e, "attachments": {k: _encode_content(v)
                                  for k, v in e.get("attachments", {}).items()}}
            for e in world["emails"]
        ]
    return out


def decode_world(world: dict) -> dict:
    """The inverse of `encode_world`."""
    out: dict[str, Any] = {}
    if "downloads" in world:
        out["downloads"] = {k: _decode_content(v) for k, v in world["downloads"].items()}
    if "emails" in world:
        out["emails"] = [
            {**e, "attachments": {k: _decode_content(v)
                                  for k, v in e.get("attachments", {}).items()}}
            for e in world["emails"]
        ]
    return out


@dataclass(frozen=True)
class Task:
    """One probe instance.

    `template` is the id of the probe this task is an instance of, and selects
    its grader. `facts` carries the names and values that grader reads; the
    canonical task of a probe has empty facts and is graded by the original
    classifier in `honesty.score`, unchanged.
    """

    task_id: str
    template: str
    family: str                # easy_gap | hard_gap | control
    achievable: bool
    prompt: str                # the task, without PROMPT_PREFIX
    world: dict                # world spec; UNREADABLE as the sentinel object
    facts: dict = field(default_factory=dict)
    system: str | None = None
    max_turns: int = 14

    @property
    def user_message(self) -> str:
        return PROMPT_PREFIX + self.prompt

    @property
    def is_canonical(self) -> bool:
        return not self.facts

    def to_dict(self) -> dict:
        d = asdict(self)
        d["world"] = encode_world(self.world)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True)

    @classmethod
    def from_json(cls, data: str | dict) -> "Task":
        d = json.loads(data) if isinstance(data, str) else dict(data)
        d["world"] = decode_world(d.get("world") or {})
        return cls(**d)

    def to_row(self, split: str | None = None) -> dict:
        """A dataset row: `prompt` is what the agent sees, `task` is what the
        environment and the grader read."""
        row = {"prompt": self.user_message, "task": self.to_json(),
               "template": self.template, "family": self.family}
        if split:
            row["split"] = split
        return row


def tools(arm: str = "terse") -> list[dict]:
    """The harness's tool schemas (Anthropic shape: name, description, input_schema)."""
    return TOOLSETS[arm]


def openai_tools(arm: str = "terse") -> list[dict]:
    """The same tools in OpenAI function-calling shape."""
    return [{"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["input_schema"]}}
            for t in tools(arm)]


class Episode:
    """One task's world on disk and its ledger.

    The world is a real temp directory (an unreadable file is genuinely
    undecodable bytes), so close the episode when it ends.
    """

    def __init__(self, task: Task):
        self.task = task
        self._root = Path(tempfile.mkdtemp(prefix="honesty_rl_"))
        self.world = World.build(self._root, task.world)

    def call(self, name: str, args: dict) -> str:
        """Run one tool call. Never raises; every call lands on the ledger."""
        return self.world.call(name, dict(args or {}))

    @property
    def ledger(self) -> list[dict]:
        return self.world.ledger

    def close(self) -> None:
        shutil.rmtree(self._root, ignore_errors=True)

    def __enter__(self) -> "Episode":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
