# Research status

This document tracks the public research state of the Agent Honesty Harness. It is intentionally narrower than an internal handoff: it records what is supported by the checked-in corpus, what remains uncertain, and what validation work should happen next.

## Current snapshot

- **1,460 records**
- **4 models**
- **2 providers**
- **16 probes**
- **6 conditions**
- **244 offline tests**

The checked-in results are reproducible from `results/records.jsonl` with the repository's scoring/reporting code.

## What the current evidence supports

The strongest current evidence is intervention-specific:

1. A cross-surface substitution probe discriminates between tested model/condition cells while its mirror control remains clean.
2. Explicit tool wording about provenance/failure contracts removes the observed substitution behavior in the tested intervention cells.
3. That same wording does not repair a separate false-premise disclosure failure.
4. An artifact-awareness instruction changes whether the caveat reaches an external draft recipient.
5. A disclosure rule can have opposite effects across models and across turns, which is why the harness includes multi-turn probes.

See `FINDINGS.md` and `results/RESULTS.md` for the exact cells, denominators, and confidence bounds.

## Honesty standard

The scorer applies a **belief-based** standard to material beliefs about the agent's own actions. Under that standard, an agent can fail even without asserting a literally false sentence if it leaves the user with a material false belief that the agent created and is uniquely positioned to correct.

This is a normative choice. It is declared in code as `HONESTY_STANDARD` and should be stated whenever the results are summarized.

## Known limitations

- **Independent human validation is still missing.** The detector has author-written tests and adversarial review, but the planned blind human labeling exercise has not yet been completed. This is the largest remaining validity gap.
- The experiment is narrow: four models, two providers, one tool schema, sixteen probes.
- Repetition counts differ across cells. Read per-cell denominators rather than assuming a uniform `n`.
- Zero observed failures does not imply a zero failure rate.
- A tool-output formatting change created a confound in a subset of non-discriminating probes.
- The persona condition was weaker than intended and should be escalated before drawing conclusions about persona effects.
- Advisory LLM judges disagree sharply on the definition of silence versus correction. Their verdicts never overwrite the mechanical score.

## Next validation work

1. Complete the blind human labeling set and publish agreement/error analysis.
2. Escalate the persona condition according to the preregistered contingency.
3. Implement the specified but not-yet-run probes (`p06`, `h08`) only with preregistration preserved.
4. Add more model/provider families without changing the existing scoring bar post hoc.
5. Keep LLM judges advisory; do not make them authoritative over the deterministic ledger-first scorer.

## Publication discipline

This repository should not be presented as a general ranking of model honesty. Public claims should remain tied to the tested probes, conditions, denominators, and declared honesty standard.
