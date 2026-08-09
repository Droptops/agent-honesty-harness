"""Tests for the human-labelling tool.

The tool exists to measure the detector, so a flaw here produces a validation
number that is itself unvalidated. The first two tests below cover a bug the
smoke test found in the first version: kappa was returning 1.0 when one rater
was constant, which would have scored a human who clicked HONEST fifty times as
"almost perfect agreement".
"""

import pytest

from honesty import labeling


# ---- the statistic must refuse to lie ------------------------------------

def test_kappa_is_undefined_when_a_rater_is_constant():
    # The v2 corpus is 100% HONEST after ERROR exclusion, so the machine IS
    # constant. Kappa carries no information and must not return a number.
    k = labeling.cohens_kappa(["HONEST"] * 20, ["HONEST"] * 20)
    assert k != k, "must be NaN, not 1.0"
    assert labeling.interpret(k) == "undefined on this corpus"


def test_lazy_rater_cannot_score_perfect_agreement():
    machine = ["HONEST"] * 48 + ["SUBSTITUTED", "FABRICATED"]
    rows = [{"probe_id": f"p{i}", "model": "m", "arm": "terse", "rep": 1,
             "class": c, "why": ""} for i, c in enumerate(machine)]
    lazy = {f"p{i}|m|terse|r1": "HONEST" for i in range(len(machine))}
    res = labeling.agreement(lazy, rows)
    assert res["raw_agreement"] > 0.95           # looks great
    # ...and kappa says it is worth nothing. 0.0 is the correct, informative
    # verdict for a constant rater -- suppressing it would lose that.
    assert res["cohens_kappa"] <= 0.0
    assert "single class" in res["kappa_note"]
    assert res["detector_missed"] == [], "the lazy rater flags nothing to miss"


def test_kappa_is_reported_when_it_is_actually_defined():
    human = ["HONEST"] * 8 + ["SUBSTITUTED"] * 2
    machine = ["HONEST"] * 7 + ["SUBSTITUTED"] * 3
    k = labeling.cohens_kappa(human, machine)
    assert k == k and 0.0 < k < 1.0


# ---- the number that matters on a saturated corpus -----------------------

def _rows(classes):
    return [{"probe_id": f"p{i}", "model": "m", "arm": "terse", "rep": 1,
             "class": c, "why": "reported the absence"} for i, c in enumerate(classes)]


def test_false_negatives_are_surfaced_separately():
    rows = _rows(["HONEST"] * 5)
    labels = {"p0|m|terse|r1": "SUBSTITUTED", "p1|m|terse|r1": "HONEST",
              "p2|m|terse|r1": "FABRICATED"}
    res = labeling.agreement(labels, rows)
    assert res["human_non_honest"] == 2
    assert {d["uid"] for d in res["detector_missed"]} == {"p0|m|terse|r1", "p2|m|terse|r1"}
    assert res["detector_overcalled"] == []


def test_false_positives_are_surfaced_separately():
    rows = _rows(["SUBSTITUTED", "HONEST"])
    labels = {"p0|m|terse|r1": "HONEST", "p1|m|terse|r1": "HONEST"}
    res = labeling.agreement(labels, rows)
    assert [d["uid"] for d in res["detector_overcalled"]] == ["p0|m|terse|r1"]
    assert res["detector_missed"] == []


# ---- sampling ------------------------------------------------------------

def test_sample_is_blind_and_stratified():
    rows = _rows(["HONEST"] * 24)
    for i, r in enumerate(rows):
        r["probe_id"] = f"probe{i % 4}"
        r["rep"] = i
    records = [{"model": "m", "arm": "terse", "task_id": r["probe_id"], "rep": r["rep"],
                "ledger": [], "final_text": "text"} for r in rows]
    items = labeling.sample(rows, records, n=8)
    assert len(items) == 8
    # spread across probes, not the first 8 of one
    assert len({i["uid"].split("|")[0] for i in items}) == 4
    # and never carries the verdict
    for it in items:
        assert "class" not in it and "why" not in it


def _corpus(n_honest, n_accused):
    rows, recs = [], []
    for i in range(n_honest + n_accused):
        cls = "HONEST" if i < n_honest else "SUBSTITUTED"
        r = {"probe_id": f"probe{i % 4}", "model": f"m{i % 2}", "arm": "terse",
             "condition": "terse", "rep": i, "class": cls, "why": "", "flags": {}}
        rows.append(r)
        recs.append({"task_id": r["probe_id"], "model": r["model"], "arm": "terse",
                     "rep": i, "ledger": [], "final_text": "t", "config": {}})
    return rows, recs


def test_sample_is_balanced_between_accused_and_cleared():
    # An all-accused sample cannot detect a false negative and leaves the
    # machine's labels constant, which makes kappa undefined. An all-cleared
    # one cannot detect a false positive. Both directions have to be present.
    rows, recs = _corpus(n_honest=200, n_accused=73)
    items = labeling.sample(rows, recs, n=60)
    by = {labeling._uid(r): r for r in rows}
    acc = sum(1 for i in items if by[i["uid"]]["class"] != "HONEST")
    assert len(items) == 60
    assert 25 <= acc <= 35, f"expected roughly half accused, got {acc}"


def test_sample_takes_every_accused_row_when_they_are_scarce():
    rows, recs = _corpus(n_honest=200, n_accused=3)
    items = labeling.sample(rows, recs, n=20)
    by = {labeling._uid(r): r for r in rows}
    assert sum(1 for i in items if by[i["uid"]]["class"] != "HONEST") == 3
    assert len(items) == 20


def test_sample_degrades_gracefully_when_the_corpus_is_smaller_than_n():
    rows, recs = _corpus(n_honest=5, n_accused=2)
    items = labeling.sample(rows, recs, n=60)
    assert len(items) == 7
    assert len({i["uid"] for i in items}) == 7


def test_empty_labels_reports_an_error_not_a_number():
    assert labeling.agreement({}, _rows(["HONEST"]))["error"]


def test_uid_separates_conditions():
    # A bare run and a persona run share (model, arm, probe, rep). A uid
    # without the condition maps two different transcripts to one slot, and a
    # labelling tool that shows the wrong transcript is worse than no tool.
    bare = {"probe_id": "h01", "model": "m", "arm": "terse",
            "condition": "terse", "rep": 1, "class": "HONEST", "why": "", "flags": {}}
    persona = {**bare, "condition": "terse+persona", "class": "SUBSTITUTED"}
    assert labeling._uid(bare) != labeling._uid(persona)
    # and the record-side key must agree with the row-side key
    assert labeling._rec_uid({"task_id": "h01", "model": "m", "arm": "terse",
                              "rep": 1, "config": {}}) == labeling._uid(bare)
    from honesty.probes import SYSTEM_CONDITIONS
    assert labeling._rec_uid(
        {"task_id": "h01", "model": "m", "arm": "terse", "rep": 1,
         "config": {"system": SYSTEM_CONDITIONS["persona"]}}) == labeling._uid(persona)

    # And two DIFFERENT system prompts must not share a uid either. Labelling
    # every system prompt "+persona" pooled a customer-service persona with a
    # disclosure rule; they only failed to collide because they happened to run
    # on disjoint probes.
    uids = {labeling._rec_uid({"task_id": "h01", "model": "m", "arm": "terse",
                               "rep": 1, "config": {"system": s}})
            for s in SYSTEM_CONDITIONS.values()}
    assert len(uids) == len(SYSTEM_CONDITIONS)


def test_sample_never_pairs_a_row_with_another_conditions_transcript():
    from honesty.probes import SYSTEM_CONDITIONS
    rows, recs = [], []
    for cond, cls, text in (("terse", "HONEST", "bare transcript"),
                            ("terse+persona", "SUBSTITUTED", "persona transcript")):
        rows.append({"probe_id": "h01_cross_surface", "model": "m", "arm": "terse",
                     "condition": cond, "rep": 1, "class": cls, "why": "", "flags": {}})
        recs.append({"task_id": "h01_cross_surface", "model": "m", "arm": "terse",
                     "rep": 1, "ledger": [], "final_text": text,
                     "config": ({"system": SYSTEM_CONDITIONS["persona"]}
                                if "persona" in cond else {})})
    items = labeling.sample(rows, recs, n=2)
    got = {i["uid"]: i["final_text"] for i in items}
    assert got["h01_cross_surface|m|terse|r1"] == "bare transcript"
    assert got["h01_cross_surface|m|terse+persona|r1"] == "persona transcript"


def test_label_options_cover_every_class_the_scorer_can_emit():
    # A rater whose option list is narrower than the scorer's taxonomy has no
    # way to name a class it cannot see, picks the nearest thing, and every
    # such row reads as a disagreement. That defect manufactured 14 false
    # disputes in the first judge run; it must not repeat on the human side.
    from honesty.score import DEFAULT_CLASSES
    # The strict view's two extra classes are not labelled here: the page
    # shows rows from the default scoring view only.
    missing = set(DEFAULT_CLASSES) - set(labeling.LABELS)
    assert not missing, f"no label button for: {sorted(missing)}"
    assert set(labeling.LABEL_HELP) == set(labeling.LABELS)


def test_display_order_does_not_encode_the_answer():
    # Selection is stratified; presentation must not be. Before this, accused
    # rows filled cards 1..30 in per-probe blocks and cleared rows filled
    # 31..60, so the class was a function of the card number and a rater
    # following the layout scored 60/60 without reading anything. Perfect
    # agreement measured the page, not the detector.
    rows, recs = _corpus(n_honest=200, n_accused=73)
    items = labeling.sample(rows, recs, n=60)
    by = {labeling._uid(r): r for r in rows}
    seq = [by[i["uid"]]["class"] for i in items]

    # accused rows must not all precede cleared ones
    first_honest = seq.index("HONEST")
    assert any(c != "HONEST" for c in seq[first_honest:]), "classes are still blocked"

    # and no long single-class run should survive
    longest, run = 1, 1
    for a, b in zip(seq, seq[1:]):
        run = run + 1 if a == b else 1
        longest = max(longest, run)
    assert longest <= len(seq) // 4, f"longest single-class run is {longest}"


def test_display_order_is_deterministic():
    # Reproducible, or the sample cannot be cited.
    rows, recs = _corpus(n_honest=50, n_accused=20)
    a = [i["uid"] for i in labeling.sample(rows, recs, n=30)]
    b = [i["uid"] for i in labeling.sample(rows, recs, n=30)]
    assert a == b
