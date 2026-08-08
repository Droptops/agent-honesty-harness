"""Provider adapters.

One job: run a tool-using conversation against a model and hand back, per turn,
(text, tool calls, stop reason, usage). Each adapter owns its own message
history because the wire formats differ; the runner never touches provider
shapes.

Anthropic is the subject-model path. OpenAI is here for the optional second
judge -- and because the adapter exists, an OpenAI subject arm is a config
change rather than a code change. Model ids are never hardcoded for OpenAI;
they are resolved against the account at runtime, so this file does not go stale
when the catalogue moves.

Keys are read from the environment and never written anywhere -- not to results,
not to logs, not to disk.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

# ---- pricing, USD per million tokens -------------------------------------
# Used only to report what a sweep cost. Wrong numbers here change no result.
PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),      # intro pricing through 2026-08-31
    "claude-opus-4-8": (5.00, 25.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def cost_usd(model: str, usage: dict | None) -> float | None:
    """Cost in USD, or None when the model's rates are not in the table.

    None rather than 0.0 on purpose. A model whose price is unknown reporting
    $0.00 is a false number in a report about false numbers -- the totals would
    silently understate, and nobody would see why. Tokens are always recorded,
    so an unpriced model can be costed later.
    """
    if not usage:
        return 0.0
    rates = PRICES.get(model.split(":", 1)[-1])
    if rates is None:
        return None
    rate_in, rate_out = rates
    return (usage.get("input_tokens", 0) * rate_in
            + usage.get("output_tokens", 0) * rate_out) / 1_000_000


@dataclass
class Turn:
    text: str
    tool_calls: list[dict]        # [{id, name, input}]
    stop_reason: str
    usage: dict = field(default_factory=dict)


def require_key(var: str) -> str:
    """Read a key from the environment, or fail with a message that says how to
    fix it. On Windows the User-scope variable does not reach an already-running
    parent process, which is the usual cause."""
    val = os.environ.get(var)
    if not val:
        raise RuntimeError(
            f"{var} is not set in this process's environment.\n"
            f"  PowerShell: $env:{var} = [Environment]::GetEnvironmentVariable('{var}','User')\n"
            f"  (a User-scope variable set after a process started is invisible to it)"
        )
    return val


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------

class AnthropicAgent:
    """A tool-using conversation with a Claude model.

    Assistant content is appended verbatim, which is what keeps thinking blocks
    intact across turns. max_tokens has to cover thinking *and* the reply --
    thinking is on by default on Opus 5 -- so it is set generously and a
    truncated turn is reported rather than scored.
    """

    def __init__(self, model: str, tools: list[dict], *, max_tokens: int = 8000,
                 effort: str | None = None, system: str | None = None):
        import anthropic

        require_key("ANTHROPIC_API_KEY")
        self.model = model
        self.tools = tools
        self.max_tokens = max_tokens
        self.effort = effort
        self.system = system
        self.messages: list[dict] = []
        self.usage = {"input_tokens": 0, "output_tokens": 0,
                      "cache_read_input_tokens": 0}
        self._client = anthropic.Anthropic(max_retries=4, timeout=180.0)

    def user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def step(self) -> Turn:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "tools": self.tools,
            "messages": self.messages,
        }
        if self.system:
            kwargs["system"] = self.system
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}

        r = self._client.messages.create(**kwargs)

        self.usage["input_tokens"] += r.usage.input_tokens or 0
        self.usage["output_tokens"] += r.usage.output_tokens or 0
        self.usage["cache_read_input_tokens"] += getattr(
            r.usage, "cache_read_input_tokens", 0) or 0

        if r.stop_reason == "refusal":
            return Turn("[refusal]", [], "refusal", dict(self.usage))

        self.messages.append({"role": "assistant", "content": r.content})
        text = "".join(b.text for b in r.content if b.type == "text")
        tool_calls = [
            {"id": b.id, "name": b.name, "input": b.input}
            for b in r.content if b.type == "tool_use"
        ]
        return Turn(text, tool_calls, r.stop_reason or "", dict(self.usage))

    def results(self, results: list[dict]) -> None:
        self.messages.append({
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"]}
                for r in results
            ],
        })


# --------------------------------------------------------------------------
# OpenAI
# --------------------------------------------------------------------------

def _openai_client():
    from openai import OpenAI

    require_key("OPENAI_API_KEY")
    kwargs: dict[str, Any] = {"max_retries": 4, "timeout": 180.0}
    if os.environ.get("OPENAI_PROJECT"):
        kwargs["project"] = os.environ["OPENAI_PROJECT"]
    return OpenAI(**kwargs)


def resolve_openai_model(preference: list[str] | None = None) -> str:
    """Pick a chat model the account can actually use.

    Model ids are not hardcoded: the account's own catalogue is the source of
    truth, so this keeps working when the catalogue moves. `preference` is
    matched as a prefix, best first.
    """
    preference = preference or ["gpt-5", "o4", "gpt-4.1", "gpt-4o", "gpt-4"]
    ids = sorted(m.id for m in _openai_client().models.list())
    for pref in preference:
        hits = [i for i in ids if i.startswith(pref)]
        if hits:
            # Shortest match is the undated alias when one exists.
            return sorted(hits, key=len)[0]
    raise RuntimeError(
        "No usable OpenAI chat model found on this account. Visible ids: "
        + ", ".join(ids[:20])
    )


def _to_openai_tools(tools: list[dict]) -> list[dict]:
    return [
        {"type": "function",
         "function": {"name": t["name"], "description": t["description"],
                      "parameters": t["input_schema"]}}
        for t in tools
    ]


class OpenAIAgent:
    """The same conversation shape against an OpenAI chat model.

    Present so the harness is not single-provider by construction. Not used by
    the default sweep.
    """

    def __init__(self, model: str, tools: list[dict], *, max_tokens: int = 8000,
                 system: str | None = None, **_ignored):
        self.model = model
        self.tools = _to_openai_tools(tools)
        self.max_tokens = max_tokens
        self.messages: list[dict] = ([{"role": "system", "content": system}]
                                     if system else [])
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self._client = _openai_client()

    def user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})

    def step(self) -> Turn:
        import json as _json

        r = self._client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            tools=self.tools,
            max_completion_tokens=self.max_tokens,
        )
        if r.usage:
            self.usage["input_tokens"] += r.usage.prompt_tokens or 0
            self.usage["output_tokens"] += r.usage.completion_tokens or 0

        choice = r.choices[0]
        msg = choice.message
        self.messages.append(msg.model_dump(exclude_none=True))
        calls = [
            {"id": tc.id, "name": tc.function.name,
             "input": _json.loads(tc.function.arguments or "{}")}
            for tc in (msg.tool_calls or [])
        ]
        return Turn(msg.content or "", calls, choice.finish_reason or "",
                    dict(self.usage))

    def results(self, results: list[dict]) -> None:
        for r in results:
            self.messages.append({"role": "tool", "tool_call_id": r["id"],
                                  "content": r["content"]})


def make_agent(model: str, tools: list[dict], **kw):
    """`openai:<id>` routes to OpenAI; anything else is Anthropic."""
    if model.startswith("openai:"):
        return OpenAIAgent(model.split(":", 1)[1], tools, **kw)
    return AnthropicAgent(model, tools, **kw)
