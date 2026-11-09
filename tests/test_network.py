"""V8 tests: the network templates and the NL rules, on the real v2 data in Neo4j.

The expected links come straight from the CSV files, computed in plain Python here.
So each template is checked against data it did not produce. No LLM is used.
"""

import csv
import json

import pytest

from src import config
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.graph.network import STRONG_LINK_TEMPLATES, find_copied_story
from src.scoring.as_of import facts_as_of
from src.scoring.engine import run_rules
from src.scoring.facts import read_raw_facts

EXACT_NL_RULES = ["NL-1", "NL-2", "NL-3", "NL-5", "NL-6"]
LOOKALIKE_GROUPS = ["family", "busy_law_firm", "busy_repair_shop", "large_clinic", "multi_claimant_incident"]


def read_table(table_name):
    with open(config.TABLES_DIR / f"{table_name}.csv", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def claim_rows_from_csv():
    """{claim ID: what the strong links compare}, from the CSV files only."""
    claimants = {row["claimant_id"]: row for row in read_table("claimants")}
    lawsuits = {row["claim_id"]: row for row in read_table("lawsuits")}
    rows = {}
    for claim in read_table("claims"):
        claimant = claimants[claim["claimant_id"]]
        lawsuit = lawsuits.get(claim["claim_id"], {})
        rows[claim["claim_id"]] = {
            "incident": claim["incident_id"], "claimant": claim["claimant_id"], "loss_date": claim["loss_date"],
            "phone": claimant["phone_number"], "address": claimant["address_id"],
            "clinic_and_attorney": (claim["clinic_id"], claim["attorney_id"]) if claim["attorney_id"] else None,
            "firm_and_expert": (lawsuit["plaintiff_law_firm_id"], lawsuit["expert_id"]) if lawsuit else None,
        }
    return rows


def expected_pairs(rows, key):
    """Every (claim, other claim) pair in different incidents with the same value of key."""
    pairs = set()
    for claim_id, row in rows.items():
        for other_id, other in rows.items():
            if other_id != claim_id and row[key] is not None and row[key] == other[key] \
                    and row["incident"] != other["incident"]:
                pairs.add((claim_id, other_id))
    return pairs


@pytest.fixture(scope="module")
def driver():
    neo4j_driver = open_neo4j_driver()
    yield neo4j_driver
    neo4j_driver.close()


@pytest.fixture(scope="module")
def truth():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


@pytest.fixture(scope="module")
def rule_results(driver, truth):
    """The current rule results of every claim (plain code, no LLM, nothing saved)."""
    results = {}
    for claim_id in truth["claims"]:
        results[claim_id] = run_rules(facts_as_of(read_raw_facts(driver, claim_id)))
    return results


# --- Each template on known data ------------------------------------------------------

@pytest.mark.parametrize("template_name, kind", [("nl_links_shared_phone", "phone"),
                                                 ("nl_links_shared_address", "address"),
                                                 ("nl_links_clinic_and_attorney", "clinic_and_attorney"),
                                                 ("nl_links_firm_and_expert", "firm_and_expert")])
def test_each_strong_link_template_matches_the_csv_files(driver, template_name, kind):
    rows = claim_rows_from_csv()
    query, _ = STRONG_LINK_TEMPLATES[template_name]
    records, _, _ = driver.execute_query(query, claim_ids=list(rows))
    found = {(record["source_claim_id"], record["linked_claim_id"]) for record in records}
    expected = expected_pairs(rows, kind)
    assert found == expected
    assert len(expected) > 0, "the template was never tested on a real link"
    assert {record["kind"] for record in records} == {kind}


def test_repeat_claims_template_matches_the_csv_files(driver):
    rows = claim_rows_from_csv()
    tested = 0
    for claim_id, row in rows.items():
        expected = {other_id for other_id, other in rows.items()
                    if other_id != claim_id and other["claimant"] == row["claimant"] and other["incident"] != row["incident"]}
        if not expected:
            continue
        records, _, _ = driver.execute_query(queries.NL_REPEAT_CLAIMS, claim_id=claim_id)
        assert {record["claim_id"] for record in records} == expected, claim_id
        tested += 1
    assert tested >= 10


def test_copied_story_template_finds_only_copies_in_the_same_story_group(driver, truth):
    found_pairs = 0
    for claim_id, claim in truth["claims"].items():
        if claim["story_group"] is None:
            continue
        for copy in find_copied_story(driver, claim_id):
            other = truth["claims"][copy["other_claim_id"]]
            assert other["story_group"] == claim["story_group"], (claim_id, copy["other_claim_id"])
            assert copy["document_type"] in config.STORY_DOCUMENT_TYPES
            assert copy["score"] >= config.SIMILARITY_THRESHOLD
            found_pairs += 1
    assert found_pairs > 50


def test_story_document_types_template(driver, truth):
    claim_id = truth["demo_claims"]["ring"]
    records, _, _ = driver.execute_query(queries.STORY_DOCUMENT_TYPES_OF_CLAIM, claim_id=claim_id,
                                         document_types=config.STORY_DOCUMENT_TYPES)
    assert [record["document_type"] for record in records] == ["fnol"]      # no lawsuit, so no complaint


def test_no_template_returns_a_link_inside_one_incident(driver):
    rows = claim_rows_from_csv()
    multi_claimant_incidents = {}
    for claim_id, row in rows.items():
        multi_claimant_incidents.setdefault(row["incident"], []).append(claim_id)
    claim_ids = [claim_id for claims in multi_claimant_incidents.values() if len(claims) > 1 for claim_id in claims]
    for query, _ in STRONG_LINK_TEMPLATES.values():
        records, _, _ = driver.execute_query(query, claim_ids=claim_ids)
        for record in records:
            assert rows[record["source_claim_id"]]["incident"] != rows[record["linked_claim_id"]]["incident"]


# --- The NL rules on the planted claims ----------------------------------------------

def test_graph_rules_fire_exactly_where_the_ground_truth_says(rule_results, truth):
    for claim_id, claim in truth["claims"].items():
        for rule_id in EXACT_NL_RULES:
            fired = rule_results[claim_id][rule_id]["status"] == "fired"
            assert fired == (rule_id in claim["planted_rules"]), (claim_id, rule_id)


def test_copied_story_rule_has_no_false_fire_and_finds_almost_all(rule_results, truth):
    planted = missed = 0
    for claim_id, claim in truth["claims"].items():
        fired = rule_results[claim_id]["NL-4"]["status"] == "fired"
        if "NL-4" in claim["planted_rules"]:
            planted += 1
            missed += not fired
        else:
            assert not fired, claim_id
    # Measured in V8: the LLM rewrote one planted pair too freely (best similarity 0.977).
    assert planted == 27 and missed <= 2


def test_every_ring_claim_with_a_planted_network_signal_fires_a_network_rule(rule_results, truth):
    # By design a ring claim shows each signal with a chance of 70 to 90% (A4). Two Ring B
    # claims (C-1144, C-1165) got no network signal at all, so they cannot fire one.
    without_signal = []
    for ring in ["ring_a", "ring_b", "ring_c"]:
        for claim_id in truth["fraud_types"][ring]:
            if not any(rule_id.startswith("NL") for rule_id in truth["claims"][claim_id]["planted_rules"]):
                without_signal.append(claim_id)
                continue
            fired = [rule_id for rule_id, result in rule_results[claim_id].items()
                     if rule_id.startswith("NL") and result["status"] == "fired"]
            assert fired, (ring, claim_id)
    assert without_signal == ["C-1144", "C-1165"]


def test_lookalikes_do_not_fire_the_ring_rules(rule_results, truth):
    checked = 0
    for claim_id, claim in truth["claims"].items():
        if claim["group"] in LOOKALIKE_GROUPS:
            for rule_id in ["NL-3", "NL-4", "NL-6"]:
                assert rule_results[claim_id][rule_id]["status"] != "fired", (claim["group"], claim_id, rule_id)
            checked += 1
    assert checked == 16 + 25 + 25 + 25 + 28
