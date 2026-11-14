"""Tests of src/scoring/facts.py (new system). They run on the real graph (Neo4j must be running).

The expected values come from the CSV files in data/tables/.
"""

import csv
import datetime

import pytest

from src import config
from src.graph.connection import open_neo4j_driver
from src.scoring.facts import read_claim_facts
from tests.test_claim_tools import read_csv
from tests.test_link_tools import expected_links


@pytest.fixture(scope="module")
def driver():
    driver = open_neo4j_driver()
    yield driver
    driver.close()


def test_the_facts_of_a_claim_match_the_csv_files(driver):
    facts = read_claim_facts(driver, "C-1088")
    claim = read_csv("claims.csv", "C-1088")[0]
    expected_visits = sorted(
        row["visit_date"] for row in read_csv("treatments.csv", "C-1088")
    )
    assert facts["claim_id"] == "C-1088"
    assert facts["loss_date"] == datetime.date.fromisoformat(claim["loss_date"])
    assert facts["attorney_retained_date"] == datetime.date.fromisoformat(
        claim["attorney_retained_date"]
    )
    assert facts["visit_dates"] == [
        datetime.date.fromisoformat(text) for text in expected_visits
    ]


def test_the_dates_are_python_dates_so_the_rules_can_subtract_them(driver):
    facts = read_claim_facts(driver, "C-1088")
    assert type(facts["loss_date"]) is datetime.date
    assert all(type(visit) is datetime.date for visit in facts["visit_dates"])
    assert (
        facts["visit_dates"][0] - facts["loss_date"]
    ).days == 8  # 2024-12-15 to 2024-12-23


def test_a_missing_attorney_date_is_none(driver):
    assert read_claim_facts(driver, "C-1001")["attorney_retained_date"] is None


def test_the_direct_links_match_the_csv_files(driver):
    for claim_id in ["C-1088", "C-1026"]:
        links = read_claim_facts(driver, claim_id)["direct_links"]
        assert {
            (link["linked_claim_id"], link["kind"]) for link in links
        } == expected_links(claim_id)
        assert all(link["shared_value"] for link in links)


def test_the_direct_links_are_not_cut_at_a_maximum(driver, monkeypatch):
    from src.tools import link_tools

    monkeypatch.setattr(
        link_tools, "MAX_LINKED_CLAIMS", 3
    )  # this cut is for the tool answer only
    assert len(read_claim_facts(driver, "C-1088")["direct_links"]) >= 10


def test_a_claim_that_is_not_in_the_graph_gives_none(driver):
    assert read_claim_facts(driver, "C-9999") is None


def date_or_none(text):
    return datetime.date.fromisoformat(text) if text else None


def test_the_reported_date_and_the_policy_dates_match_the_csv_files(driver):
    with open(config.TABLES_DIR / "policies.csv", encoding="utf-8") as file:
        policies = {row["policy_id"]: row for row in csv.DictReader(file)}
    for claim_id in ["C-1001", "C-1088", "C-1026", "C-1123"]:
        facts = read_claim_facts(driver, claim_id)
        claim = read_csv("claims.csv", claim_id)[0]
        policy = policies[claim["policy_id"]]
        assert facts["reported_date"] == date_or_none(claim["reported_date"])
        for key in [
            "effective_date",
            "expiration_date",
            "customer_since",
            "last_coverage_increase_date",
            "lapse_start",
            "lapse_end",
        ]:
            assert facts["policy"][key] == date_or_none(policy[key]), (claim_id, key)


def test_the_lawsuits_match_the_csv_files(driver):
    with open(config.TABLES_DIR / "lawsuits.csv", encoding="utf-8") as file:
        lawsuits = list(csv.DictReader(file))
    claim_id = lawsuits[0]["claim_id"]
    expected = sorted(
        (
            row["lawsuit_id"],
            date_or_none(row["filed_date"]),
            date_or_none(row["limitation_deadline"]),
        )
        for row in lawsuits
        if row["claim_id"] == claim_id
    )
    facts = read_claim_facts(driver, claim_id)
    assert (
        sorted(
            (law["lawsuit_id"], law["filed_date"], law["limitation_deadline"])
            for law in facts["lawsuits"]
        )
        == expected
    )


def test_the_payments_and_reserve_events_match_the_csv_files_and_are_sorted_by_date(
    driver,
):
    for claim_id in ["C-1088", "C-1026", "C-1123"]:
        facts = read_claim_facts(driver, claim_id)
        expected_payments = sorted(
            (
                row["payment_id"],
                row["payment_date"],
                float(row["amount"]),
                row["payment_type"],
            )
            for row in read_csv("payments.csv", claim_id)
        )
        assert (
            sorted(
                (
                    p["payment_id"],
                    p["payment_date"].isoformat(),
                    p["amount"],
                    p["payment_type"],
                )
                for p in facts["payments"]
            )
            == expected_payments
        )
        payment_dates = [p["payment_date"] for p in facts["payments"]]
        assert payment_dates == sorted(payment_dates)
        expected_reserves = sorted(
            (row["event_id"], row["event_date"], float(row["reserve_total"]))
            for row in read_csv("reserve_events.csv", claim_id)
        )
        assert (
            sorted(
                (e["event_id"], e["event_date"].isoformat(), e["reserve_total"])
                for e in facts["reserve_events"]
            )
            == expected_reserves
        )
        reserve_dates = [e["event_date"] for e in facts["reserve_events"]]
        assert reserve_dates == sorted(reserve_dates)


def test_the_repair_estimate_matches_the_csv_files(driver):
    for claim_id in ["C-1088", "C-1026"]:
        claim = read_csv("claims.csv", claim_id)[0]
        expected = (
            float(claim["repair_estimate_amount"])
            if claim["repair_estimate_amount"]
            else None
        )
        assert read_claim_facts(driver, claim_id)["repair_estimate_amount"] == expected


def test_the_repeat_claims_match_the_csv_files(driver):
    with open(config.TABLES_DIR / "claims.csv", encoding="utf-8") as file:
        claims = {row["claim_id"]: row for row in csv.DictReader(file)}
    checked_with_repeats = 0
    for claim_id in [f"C-{number}" for number in range(1001, 1501, 3)]:
        own = claims[claim_id]
        expected = sorted(
            (other["claim_id"], other["loss_date"])
            for other in claims.values()
            if other["claimant_id"] == own["claimant_id"]
            and other["claim_id"] != claim_id
            and not (own["incident_id"] and other["incident_id"] == own["incident_id"])
        )
        facts = read_claim_facts(driver, claim_id)
        assert (
            sorted(
                (c["claim_id"], c["loss_date"].isoformat())
                for c in facts["repeat_claims"]
            )
            == expected
        ), claim_id
        checked_with_repeats += len(expected) > 0
    assert (
        checked_with_repeats > 0
    )  # the comparison saw at least one real repeat claimant


def test_the_firm_and_expert_links_carry_the_filed_dates_of_both_suits(driver):
    with open(config.TABLES_DIR / "lawsuits.csv", encoding="utf-8") as file:
        filed = {}
        for row in csv.DictReader(file):
            filed.setdefault(row["claim_id"], set()).add(
                date_or_none(row["filed_date"])
            )
    found = 0
    for number in range(1001, 1501):
        claim_id = f"C-{number}"
        if not any(kind == "firm_and_expert" for _, kind in expected_links(claim_id)):
            continue
        for link in read_claim_facts(driver, claim_id)["direct_links"]:
            if link["kind"] == "firm_and_expert":
                assert link["source_filed_date"] in filed[claim_id]
                assert link["linked_filed_date"] in filed[link["linked_claim_id"]]
                found += 1
        if found >= 5:
            break
    assert found > 0


def test_the_cluster_contains_the_claim_itself_and_is_sorted(driver):
    cluster = read_claim_facts(driver, "C-1088")["cluster_claim_ids"]
    assert "C-1088" in cluster
    assert cluster == sorted(cluster)
    assert (
        len(cluster) >= len(read_claim_facts(driver, "C-1088")["direct_links"]) // 4
    )  # sanity: not empty
