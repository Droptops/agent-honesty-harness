# labels.json — scored 60/60, kappa 1.0, and NOT usable as validation

Submitted against the first version of `labeling.html`, whose **display order
encoded the answer**: the sample was selected stratified but presented
unshuffled, so cards 1–30 were the rows the scorer had accused (in tight
per-probe blocks) and cards 31–60 were all rows it had cleared.

The class was therefore a deterministic function of the card number. A rater
following the visible structure scores 60/60 without reading a transcript, and
a rater reading every transcript carefully also scores 60/60. **The two are not
distinguishable from the result**, which is what makes the number unusable —
independent of how these particular labels were produced.

This is a flaw in the page, not a claim about the labels.

Kept for provenance. Do not cite it, and do not fold it into any agreement
statistic. `labeling.sample()` now shuffles the display order by a stable digest
of each row's uid — deterministic, so the sample stays reproducible, but the
class is no longer recoverable from position. A re-label against the shuffled
page would be citable.
