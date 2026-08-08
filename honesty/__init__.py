"""Agent honesty harness.

Measures whether an agent's final claim matches what its tools actually did --
not whether its answer was correct. The failure it targets is *substitution*:
the agent lacks access, finds a plausible same-shaped artifact, uses that, and
reports success.

Entry point: `python -m honesty --help`
"""

__version__ = "2.0.0"
