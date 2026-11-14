"""Tests of src/scoring/findings.py (new system).

The merge tests use made-up findings and need no Neo4j; the expected winners are worked out by hand.
The last tests use the real graph.
"""

import datetime

import pytest

from src.scoring import findings


def finding(feature, rank, day=None, confidence="High", document_id="D1", page=1):
    note_date = datetime.date(2025, 1, day) if day else None
    return {
        "feature": feature,
        "severity_rank": rank,
        "value": f"rank{rank}",
        "note_date": note_date,
        "confidence": confidence,
        "document_id": document_id,
        "page_number": page,
    }


def test_worst_keeps_the_most_suspicious_even_if_older():
    # treatment_growth is "worst": rank 2 wins over the newer rank 1.
    merged = findings.merge_findings(
        [finding("treatment_growth", 2, day=1), finding("treatment_growth", 1, day=9)]
    )
    assert merged["treatment_growth"]["severity_rank"] == 2


def test_latest_keeps_the_newest_even_if_less_suspicious():
    # injury_crash_fit is "latest": the finding of 9 January wins.
    merged = findings.merge_findings(
        [finding("injury_crash_fit", 3, day=1), finding("injury_crash_fit", 0, day=9)]
    )
    assert merged["injury_crash_fit"]["note_date"].day == 9


def test_latest_without_a_date_is_oldest_and_ties_use_document_then_page():
    merged = findings.merge_findings(
        [finding("injury_crash_fit", 3), finding("injury_crash_fit", 0, day=2)]
    )
    assert merged["injury_crash_fit"]["severity_rank"] == 0
    merged = findings.merge_findings(
        [finding("injury_crash_fit", 1, page=1), finding("injury_crash_fit", 2, page=2)]
    )
    assert merged["injury_crash_fit"]["page_number"] == 2


def test_a_feature_without_findings_is_missing_and_an_unknown_feature_is_ignored():
    merged = findings.merge_findings([finding("not_a_feature", 1)])
    assert merged == {}


@pytest.mark.parametrize(
    "confidence, expected",
    [("High", True), ("Medium", True), ("Low", False), ("Maybe", False)],
)
def test_the_confidence_filter(confidence, expected):
    assert (
        findings.is_strong_enough(finding("driver_status", 0, confidence=confidence))
        is expected
    )


# --- With the real graph, and the old code as reference ---


@pytest.fixture(scope="module")
def driver():
    from src.graph.connection import open_neo4j_driver

    driver = open_neo4j_driver()
    yield driver
    driver.close()


def test_the_ring_claim_findings(driver):
    merged, weak = findings.usable_and_weak_findings(driver, "C-1088")
    assert merged["treatment_growth"]["value"] == "Disproportionate"
    assert merged["objective_support"]["value"] == "Predominantly subjective"
    assert weak == []
