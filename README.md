# Agent Honesty Harness

[![CI](https://github.com/Droptops/agent-honesty-harness/actions/workflows/ci.yml/badge.svg)](https://github.com/Droptops/agent-honesty-harness/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A reproducible research harness for a narrow question:

> **When an agent says it completed an action, does that claim match what its tools actually did?**

The harness targets **action-reporting failures** such as substitution, fabrication, non-attempt, and failure to correct a material false belief about the agent's own actions. It evaluates claims against a deterministic tool ledger; no LLM judge is authoritative in the scoring path.

This repository is a **research artifact, not a production safety control or a general model leaderboard**. The current corpus covers four models, two providers, one tool schema, and sixteen probes. Results should be read at the probe/condition level with their denominators and stated limitations.

## Why this exists

A common agent failure is not making up a fact. It is **substitution**: the requested artifact is unavailable, a plausible same-shaped artifact is available, the agent uses that instead, and then reports success without disclosing the mismatch.

That behavior is mechanically testable when the environment records what actually happened. The harness therefore separates:

- the **tool ledger** — ground truth about executed actions;
- the **agent's final claim** — what the user is told happened;
- the **scorer** — deterministic classifiers that compare the two.

## Quick start

Python 3.10+.

```bash
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1

pip install -r requirements.txt
python -m honesty selftest
python -m honesty baselines
```

The two commands above require no API keys and are the same preflight gate used before paid model runs.

To run the sweep:

```bash
export ANTHROPIC_API_KEY=...
export OPENAI_API_KEY=...   # needed for the OpenAI arm / optional dual judge
python -m honesty run --reps 5
python -m honesty report
```

Or run the full sequence:

```bash
python -m honesty all --reps 5
```

For blind human labeling:

```bash
python -m honesty label
```

## Current research snapshot

The checked-in corpus contains **1,460 records across 4 models, 2 providers, 16 probes, and 6 conditions**. Fourteen probes are floor checks in the current sweep; two probes materially discriminate between conditions/models.

The strongest result is intervention-specific rather than model-specific: **tool wording that explicitly states the provenance/failure contract can eliminate the observed substitution behavior in the tested cells, while leaving a different disclosure failure unchanged.** A separate artifact-awareness instruction changes whether a caveat reaches the external draft recipient.

See:

- [`FINDINGS.md`](FINDINGS.md) — standalone findings and interpretation;
- [`results/RESULTS.md`](results/RESULTS.md) — full results with intervals and denominators;
- [`STATUS.md`](STATUS.md) — current research state and known limitations;
- [`PREREGISTRATION.md`](PREREGISTRATION.md) — preregistration and amendments.

### Important interpretation rule

Do **not** read the checked-in tables as a general ranking of model honesty. The study is intentionally narrow, the detector still needs independent human validation, and zero observed failures in a cell is not a zero failure rate.

## Honesty standard

The harness currently applies a **belief-based** standard for material beliefs about the agent's own actions: a response can fail even if it contains no literally false sentence when the agent leaves the user with a material false belief that the agent created and is uniquely positioned to correct.

That is a normative choice, not an empirical measurement. The code makes it explicit as `HONESTY_STANDARD`, and the repository reports disagreement from advisory LLM judges rather than using those judges to overwrite the mechanical score.

## Repository map

| Path | Purpose |
|---|---|
| `honesty/` | Harness implementation |
| `tests/` | Offline scorer/oracle tests |
| `results/` | Raw records, derived scores, summaries, and human-labeling artifacts |
| `FINDINGS.md` | Public research writeup |
| `STATUS.md` | Current state, caveats, and next validation work |
| `PREREGISTRATION.md` | Frozen bar and amendments |
| `v1/` | Superseded prototype retained for provenance |
| `.github/workflows/ci.yml` | Offline CI across supported Python versions |

The score files are derived from `results/records.jsonl`; scoring changes do not require re-running paid model calls.

## Design properties

**Ledger first.** Tool execution is the source of truth. The scorer never infers whether an action happened from the model's prose alone.

**`SUBSTITUTED` is distinct from `FABRICATED`.** Using the wrong real artifact and inventing an artifact are different operational failures and need different mitigations.

**`AMBIGUOUS` is a real outcome.** Hedged or indeterminate claims are not forced into a pass/fail bucket.

**Mirrored controls.** Gap probes have controls intended to catch strategies such as blanket refusal, blanket caveating, or indiscriminate correction.

**Offline gates before spend.** `python -m honesty selftest` and `python -m honesty baselines` run without API access, and `honesty all` refuses to proceed to paid calls if the preflight fails.

## LLM judges

`honesty/judge.py` is optional and advisory. Judge outputs are stored separately and **never modify the authoritative class or rates**.

The current judge audit is useful precisely because the judges disagree on the normative boundary around silence versus correction. That disagreement is reported as evidence about the definition, not as validation of the scorer.

## Known limitations

- The detector has not yet been independently validated with the planned blind human labeling set.
- The study covers only four models, two providers, one tool schema, and sixteen probes.
- Some conditions have small sample sizes; read the per-cell denominators and confidence bounds.
- One tool-output formatting change created a confound in a subset of non-discriminating probes.
- The persona condition is weaker than intended and should be treated as an escalation target, not a negative finding about personas generally.
- This harness measures a narrow class of action-reporting honesty failures; it does not establish that a model or agent is globally "honest."

## Reproducibility and secrets

API credentials are read from environment variables and should never be committed. The repository intentionally checks in the research corpus needed to reproduce scoring and reports.

If you believe sensitive information or a credential has been committed, do not open a public issue; follow [`SECURITY.md`](SECURITY.md).

## Contributing

Contributions that improve scorer validity, probe design, portability, or independent labeling are welcome. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md) before opening a pull request.

## License

MIT — see [`LICENSE`](LICENSE).
