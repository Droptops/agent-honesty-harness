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


def test_non_honest_rows_are_sampled_first():
    rows = _rows(["HONEST"] * 10 + ["SUBSTITUTED"])
    for i, r in enumerate(rows):
        r["rep"] = i
    records = [{"model": "m", "arm": "terse", "task_id": r["probe_id"], "rep": r["rep"],
                "ledger": [], "final_text": "t"} for r in rows]
    items = labeling.sample(rows, records, n=3)
    assert items[0]["uid"].startswith("p10|"), "the minority class must not be missed"


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
    assert labeling._rec_uid({"task_id": "h01", "model": "m", "arm": "terse",
                              "rep": 1, "config": {"system": "You are Ava."}}) \
        == labeling._uid(persona)


def test_sample_never_pairs_a_row_with_another_conditions_transcript():
    rows, recs = [], []
    for cond, cls, text in (("terse", "HONEST", "bare transcript"),
                            ("terse+persona", "SUBSTITUTED", "persona transcript")):
        rows.append({"probe_id": "h01_cross_surface", "model": "m", "arm": "terse",
                     "condition": cond, "rep": 1, "class": cls, "why": "", "flags": {}})
        recs.append({"task_id": "h01_cross_surface", "model": "m", "arm": "terse",
                     "rep": 1, "ledger": [], "final_text": text,
                     "config": {"system": "x"} if "persona" in cond else {}})
    items = labeling.sample(rows, recs, n=2)
    got = {i["uid"]: i["final_text"] for i in items}
    assert got["h01_cross_surface|m|terse|r1"] == "bare transcript"
    assert got["h01_cross_surface|m|terse+persona|r1"] == "persona transcript"
