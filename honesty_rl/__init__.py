"""Reinforcement-learning tasks built from the honesty harness.

`honesty` is the frozen experiment. This package reuses its world, tools and
claim detectors to make training tasks, and never changes how the published
probes are scored: a canonical task is graded by `honesty.score` itself.

  spec       the Task format, the tools, and Episode (a world plus its ledger)
  variants   per-probe task generators and the variant graders
  grade      verdict for a finished episode, and the reward it earns
  generate   writes train and test JSONL datasets
"""

from .grade import grade, objective
from .spec import PROMPT_PREFIX, Episode, Task, openai_tools, tools

__all__ = ["Episode", "PROMPT_PREFIX", "Task", "grade", "objective",
           "openai_tools", "tools"]
