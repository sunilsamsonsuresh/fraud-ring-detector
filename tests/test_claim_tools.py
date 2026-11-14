"""Tests of src/tools/claim_tools.py (new system). They run on the real graph (Neo4j must be running).

The expected values come from the CSV files in data/tables/, not from the tool.
"""

import csv
import json

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.tools.claim_tools import get_claim_record


def read_csv(file_name, claim_id):
    with open(config.TABLES_DIR / file_name, encoding="utf-8") as file:
        return [row for row in csv.DictReader(file) if row["claim_id"] == claim_id]


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def test_the_record_of_a_claim_matches_the_csv_files(driver):
    result = get_claim_record(driver, "C-1088")
    facts = result["facts"]
    claim = read_csv("claims.csv", "C-1088")[0]
    visit_dates = sorted(
        row["visit_date"] for row in read_csv("treatments.csv", "C-1088")
    )
    payments = [float(row["amount"]) for row in read_csv("payments.csv", "C-1088")]
    reserve_events = read_csv("reserve_events.csv", "C-1088")

    assert facts["claim_id"] == "C-1088"
    assert facts["loss_date"] == claim["loss_date"] == "2024-12-15"
    assert facts["reported_date"] == claim["reported_date"]
    assert facts["attorney_retained_date"] == claim["attorney_retained_date"]
    assert facts["repair_estimate_amount"] == float(claim["repair_estimate_amount"])
    assert facts["incident_id"] == claim["incident_id"]
    assert facts["policy"]["policy_id"] == claim["policy_id"]
    assert facts["treatment"] == {
        "visit_count": len(visit_dates),
        "first_visit_date": visit_dates[0],
        "last_visit_date": visit_dates[-1],
    }
    assert facts["payments"] == {
        "payment_count": len(payments),
        "total_paid": round(sum(payments), 2),
    }
    assert facts["reserve"]["event_count"] == len(reserve_events)
    assert facts["lawsuits"] == []
    assert result["sources"] and result["notes"]


def test_a_claim_without_an_attorney_date_gives_none(driver):
    facts = get_claim_record(driver, "C-1001")["facts"]
    assert read_csv("claims.csv", "C-1001")[0]["attorney_retained_date"] == ""
    assert facts["attorney_retained_date"] is None


def test_a_lawsuit_is_in_the_record(driver):
    with open(config.TABLES_DIR / "lawsuits.csv", encoding="utf-8") as file:
        lawsuit = next(csv.DictReader(file))
    facts = get_claim_record(driver, lawsuit["claim_id"])["facts"]
    assert [item["lawsuit_id"] for item in facts["lawsuits"]] == [lawsuit["lawsuit_id"]]
    assert facts["lawsuits"][0]["filed_date"] == lawsuit["filed_date"]


def test_the_result_can_be_sent_as_json(driver):
    json.dumps(
        get_claim_record(driver, "C-1088")
    )  # a Neo4j date object here would raise TypeError


@pytest.mark.parametrize("claim_id", ["C-9999", "MATCH (n) DETACH DELETE n"])
def test_a_missing_claim_or_query_text_gives_a_message_and_changes_nothing(
    driver, claim_id
):
    before, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    result = get_claim_record(driver, claim_id)
    after, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes")
    assert result == {"message": f"Claim {claim_id} was not found in the graph."}
    assert after[0]["nodes"] == before[0]["nodes"]


# --- get_claim_findings ---


def test_the_findings_of_a_claim_have_a_rating_a_quote_and_a_page(driver):
    from src.tools.claim_tools import MAX_QUOTE_CHARACTERS, get_claim_findings

    answer = get_claim_findings(driver, "C-1088")
    findings = answer["facts"]["findings"]
    records, _, _ = driver.execute_query(
        "MATCH (:Claim {claim_id: 'C-1088'})-[:HAS_FINDING]->(f:Finding) RETURN count(f) AS n"
    )
    assert answer["facts"]["finding_count"] == len(findings) == records[0]["n"]
    for finding in findings:
        assert (
            finding["rating"]
            and finding["confidence"]
            and finding["document_id"].startswith("C-1088-")
        )
        assert (
            finding["page_number"] is not None
            and len(finding["quote"]) <= MAX_QUOTE_CHARACTERS
        )
    assert any(
        f["feature"] == "objective_support"
        and f["rating"] == "Predominantly subjective"
        for f in findings
    )


def test_the_most_serious_findings_come_first_and_sources_have_no_repeats(driver):
    from src.tools.claim_tools import get_claim_findings

    answer = get_claim_findings(driver, "C-1088")
    ranks = []
    for finding in answer["facts"]["findings"]:
        records, _, _ = driver.execute_query(
            "MATCH (f:Finding {feature: $feature, value: $value}) RETURN toInteger(f.severity_rank) AS rank LIMIT 1",
            feature=finding["feature"],
            value=finding["rating"],
        )
        ranks.append(records[0]["rank"])
    assert ranks == sorted(ranks, reverse=True)
    assert len(answer["sources"]) == len(set(answer["sources"]))


def test_findings_of_a_missing_claim_give_a_message(driver):
    from src.tools.claim_tools import get_claim_findings

    assert get_claim_findings(driver, "C-9999") == {
        "message": "Claim C-9999 was not found in the graph."
    }
