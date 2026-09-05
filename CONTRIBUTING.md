# Contributing

Contributions are welcome, especially work that improves validity, reproducibility, portability, or independent review.

## Before opening a pull request

Run the offline gate:

```bash
pip install -r requirements.txt
python -m honesty selftest
python -m honesty baselines
```

No API keys are required for these checks.

## Research changes

Changes to probes, scoring rules, taxonomies, thresholds, or reporting semantics can change the meaning of the experiment. Please:

1. Explain the hypothesis or defect being addressed.
2. State whether the change can move previously reported results.
3. Add or update tests for both false-positive and false-negative behavior.
4. Preserve preregistration history; do not silently rewrite a frozen decision rule after seeing results.
5. Regenerate derived result files only when the underlying scoring/reporting change requires it, and describe exactly what changed.

## Code changes

Keep the harness direct and inspectable. Avoid adding agent frameworks or hidden middleware between the model adapter and the instrumented world unless the research question explicitly requires it.

Prefer small pull requests with deterministic tests. Paid API runs should not be required to review ordinary code changes.

## Results and claims

Do not describe a clean cell as a zero failure rate. Report the observed count, denominator, and uncertainty. Do not generalize the checked-in experiment into a global ranking of model honesty.

The current scorer uses a declared belief-based honesty standard. If a contribution proposes another standard, treat it as a separate interpretation rather than silently changing the existing one.

## Sensitive information

Never commit API keys, credentials, private conversation links, or non-public artifacts. If sensitive information is discovered in the repository or its history, follow `SECURITY.md` instead of opening a public issue.
