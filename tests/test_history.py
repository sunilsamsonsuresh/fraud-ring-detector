"""V9 tests: the score over time, with no look-ahead.

The first tests use one made-up claim (RAW, the shape read_raw_facts returns), so the
expected answers are known. The last tests use Neo4j and the real demo claims. No LLM.
"""

import copy
import datetime
import json

import pytest

from src import config
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.scoring.as_of import facts_as_of
from src.scoring.engine import score_claim
from src.scoring.facts import read_raw_facts
from src.scoring.history import event_dates, peak_index, save_history, score_history, trend_of

LOSS = datetime.date(2024, 3, 1)


def day(offset):
    return LOSS + datetime.timedelta(days=offset)


def raw_finding(code, value, rank, document_type, note_date):
    return {"finding_id": f"C-TEST-{document_type}-p1-{code}", "feature": code, "value": value,
            "severity_rank": rank, "confidence": "High", "quote": f"A quote about {code}.", "page_number": 1,
            "note_date": note_date, "document_id": f"C-TEST-{document_type}", "document_type": document_type}


def link(linked_claim_id, kind, reported_offset, source="C-TEST"):
    return {"source_claim_id": source, "linked_claim_id": linked_claim_id, "kind": kind, "shared_value": "shared",
            "linked_reported_date": day(reported_offset), "source_filed_date": None, "linked_filed_date": None}


RAW = {
    "claim_id": "C-TEST", "loss_date": LOSS, "reported_date": day(2), "attorney_retained_date": None,
    "repair_estimate_amount": None,
    "policy": {"policy_id": "P-1", "effective_date": datetime.date(2023, 6, 1),
               "expiration_date": datetime.date(2024, 6, 1), "customer_since": datetime.date(2020, 1, 1),
               "last_coverage_increase_date": None, "lapse_start": None, "lapse_end": None},
    "incident_id": "I-1", "incident_claimants": {"CL-1": day(2), "CL-2": day(20)},
    "visit_dates": [day(0), day(3), day(10)],
    "payments": [{"payment_id": "PAY-1", "payment_date": day(40), "amount": 500.0, "payment_type": "medical"}],
    "reserve_events": [{"event_id": "RE-1", "event_date": day(2), "reserve_total": 5000.0}],
    "lawsuits": [],
    "document_loss_dates": [{"document_id": "C-TEST-police_report", "document_type": "police_report",
                             "loss_date_in_pdf": LOSS, "page_number": 1, "conflict": False}],
    "all_findings": [
        raw_finding("occurrence_support", "Confirmed", 0, "adjuster_file", day(5)),
        # A medical treatment summary is known only after the last visit (day 10).
        raw_finding("treatment_growth", "Disproportionate", 2, "medical_records", None),
        raw_finding("occupants_listed", 1, None, "police_report", LOSS),
    ],
    "network": {"direct_links": [link("C-PHONE", "phone", 30)], "cluster_links": [link("C-PHONE", "phone", 30)],
                "reported_dates": {"C-PHONE": day(30)}, "repeat_claims": [], "copied_story": [],
                "story_document_types": ["fnol"]},
}


def test_facts_as_of_hide_every_kind_of_future_fact():
    early = facts_as_of(RAW, day(5))
    assert early["visit_dates"] == [day(0), day(3)]
    assert early["payments"] == []                                  # paid on day 40
    assert "treatment_growth" not in early["findings"]              # medical summary: after the last visit
    assert early["findings"]["occurrence_support"]["value"] == "Confirmed"   # note of day 5
    assert early["incident_claimant_count"] == 1                    # the second claimant reports on day 20
    assert early["strong_links"] == [] and early["cluster_claim_ids"] == ["C-TEST"]   # C-PHONE reports on day 30
    everything = facts_as_of(RAW)
    assert everything["visit_dates"] == RAW["visit_dates"] and len(everything["payments"]) == 1
    assert everything["findings"]["treatment_growth"]["value"] == "Disproportionate"
    assert everything["incident_claimant_count"] == 2 and len(everything["strong_links"]) == 1


def test_event_dates_start_at_the_reported_date():
    dates = event_dates(RAW)
    assert dates[0] == day(2)                    # the visit on day 0 is known only from the report
    assert dates == [day(2), day(3), day(5), day(10), day(20), day(30), day(40)]


def test_the_score_rises_as_facts_arrive():
    history = score_history(RAW)
    fired = {snapshot["as_of_date"]: [rule["rule_id"] for rule in snapshot["result"]["fired_rules"]]
             for snapshot in history}
    assert fired[day(2)] == []
    assert fired[day(10)] == ["BI-2"]                     # the medical summary arrives
    assert fired[day(20)] == ["BI-2", "AS-6"]             # 2 claimants, 1 occupant
    assert fired[day(30)] == ["BI-2", "AS-6", "NL-1"]     # the phone link arrives


def test_adding_a_future_fact_does_not_change_past_scores():
    before = score_history(RAW)
    with_future = copy.deepcopy(RAW)
    # Three payments within 14 days (BF-3), all after the last event date of RAW.
    for offset in [100, 105, 110]:
        with_future["payments"].append({"payment_id": f"PAY-{offset}", "payment_date": day(offset),
                                        "amount": 100.0, "payment_type": "medical"})
    after = score_history(with_future)
    assert after[:len(before)] == before                  # every past snapshot is exactly the same
    assert [snapshot["as_of_date"] for snapshot in after[len(before):]] == [day(100), day(105), day(110)]
    assert "BF-3" in [rule["rule_id"] for rule in after[-1]["result"]["fired_rules"]]


def made_up_history(*points):
    return [{"as_of_date": day(offset), "result": {"total_score": score}} for offset, score in points]


def test_peak_and_trend():
    assert config.TREND_DAYS == 90 and config.TREND_MIN_CHANGE == 2.0
    history = made_up_history((0, 5.0), (50, 12.0), (80, 12.0), (200, 9.0))
    assert peak_index(history) == 1                       # the FIRST snapshot with the highest score
    # Latest = day 200 (9.0). 90 days earlier = day 110: the last snapshot by then is day 80 (12.0).
    assert trend_of(history) == "declining"
    assert trend_of(made_up_history((0, 5.0), (150, 7.0))) == "rising"
    assert trend_of(made_up_history((0, 5.0), (150, 6.9))) == "stable"
    assert trend_of(made_up_history((0, 3.0), (30, 9.0))) == "rising"    # shorter than 90 days: from the start


# --- With Neo4j and the real demo claims ---------------------------------------------

@pytest.fixture(scope="module")
def truth():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


def test_demo_claims_history_ends_at_the_current_score_and_has_one_peak(truth):
    driver = open_neo4j_driver()
    try:
        for claim_id in truth["demo_claims"].values():
            raw = read_raw_facts(driver, claim_id)
            history = score_history(raw)
            save_history(driver, claim_id, history)
            current = score_claim(driver, claim_id, datetime.date.today(), save=False)
            assert history[-1]["result"]["total_score"] == current["total_score"], claim_id
            records, _, _ = driver.execute_query(queries.SNAPSHOTS_OF_CLAIM, claim_id=claim_id)
            saved = {record["snapshot_id"]: record for record in records}
            for snapshot in history:
                assert f"{claim_id}-{snapshot['as_of_date'].isoformat()}" in saved
            assert sum(1 for record in records if record["is_peak"]) == 1, claim_id
    finally:
        driver.close()


def test_the_ring_claim_rises_over_time(truth):
    driver = open_neo4j_driver()
    try:
        history = score_history(read_raw_facts(driver, truth["demo_claims"]["ring"]))
    finally:
        driver.close()
    scores = [snapshot["result"]["total_score"] for snapshot in history]
    assert max(scores) > scores[0]
