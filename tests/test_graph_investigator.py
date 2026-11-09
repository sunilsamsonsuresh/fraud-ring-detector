"""Step 5 and V8 tests: the round 2 query templates and the Graph Investigator agent.

Needs Neo4j with the v2 data. The expected links come straight from the CSV files.
A fake LLM replaces the real one, so these tests cost nothing.
Round 1 runs the network templates with plain code (tested in tests/test_network.py).
Round 2 lets the LLM choose from the fixed list in src/graph/investigation.py.
"""

import csv
import json

import pytest

from src import config
from src.agents import graph_investigator
from src.graph import investigation
from src.graph.connection import open_neo4j_driver
from src.graph.loader import count_graph

ROUND_TWO = {"loop_count": 1, "challenger_review": {"follow_up_question": "Who else shares a clinic?"}}


def read_table(table_name):
    with open(config.TABLES_DIR / f"{table_name}.csv", newline="", encoding="utf-8") as csv_file:
        return list(csv.DictReader(csv_file))


def shared_key_by_claim():
    """{template name: {claim_id: the value that template compares}} built from the CSV files only."""
    claimants = {row["claimant_id"]: row for row in read_table("claimants")}
    firm_of_attorney = {row["attorney_id"]: row["law_firm_id"] for row in read_table("attorneys")}
    expert_of_claim = {row["claim_id"]: row["expert_id"] for row in read_table("lawsuits")}
    keys = {name: {} for name in investigation.LINK_TEMPLATES}
    for claim in read_table("claims"):
        claim_id = claim["claim_id"]
        claimant = claimants[claim["claimant_id"]]
        keys["claims_sharing_phone"][claim_id] = claimant["phone_number"]
        keys["claims_sharing_address"][claim_id] = claimant["address_id"]
        keys["claims_sharing_repair_shop"][claim_id] = claim["repair_shop_id"]
        keys["claims_sharing_clinic"][claim_id] = claim["clinic_id"]
        keys["claims_sharing_law_firm"][claim_id] = firm_of_attorney.get(claim["attorney_id"], "")
        keys["claims_sharing_expert"][claim_id] = expert_of_claim.get(claim_id, "")
    return keys


@pytest.fixture(scope="module")
def truth():
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


@pytest.fixture(scope="module")
def test_claim_ids(truth):
    """One claim of each ring and one family claim: together they use every template."""
    family = sorted(claim_id for claim_id, claim in truth["claims"].items() if claim["group"] == "family")
    return [truth["fraud_types"][ring][0] for ring in ["ring_a", "ring_b", "ring_c"]] + family[:1]


@pytest.fixture(scope="module")
def driver():
    neo4j_driver = open_neo4j_driver()
    yield neo4j_driver
    neo4j_driver.close()


def fake_llm_answer(answer_text):
    calls = []

    def fake_ask_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        calls.append(user_prompt)
        return answer_text
    return fake_ask_llm, calls


def test_each_template_alone_matches_the_csv_files(driver, test_claim_ids):
    keys = shared_key_by_claim()
    for template_name, key_of_claim in keys.items():
        links_found_somewhere = 0
        for claim_id in test_claim_ids:
            expected = set()
            if key_of_claim[claim_id] != "":
                for other_claim_id, other_key in key_of_claim.items():
                    if other_claim_id != claim_id and other_key == key_of_claim[claim_id]:
                        expected.add(other_claim_id)
            links = investigation.run_link_template(driver, template_name, [claim_id])
            assert {link["linked_claim_id"] for link in links} == expected, f"{template_name} {claim_id}"
            assert all(link["source_claim_id"] == claim_id for link in links)
            links_found_somewhere += len(links)
        assert links_found_somewhere > 0, f"{template_name} was never tested on a real link"


def test_unknown_template_and_bad_hops_are_refused(driver, test_claim_ids):
    with pytest.raises(ValueError):
        investigation.run_link_template(driver, "MATCH (n) DETACH DELETE n", [test_claim_ids[0]])
    for bad_hops in [0, 4, True, "2", 2.0, None]:
        with pytest.raises(ValueError):
            investigation.expand_linked_claims(driver, test_claim_ids[0], bad_hops)


def test_round_one_runs_every_network_template_without_the_llm(driver, truth, monkeypatch):
    fake_ask_llm, calls = fake_llm_answer("{}")
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    ring_a = truth["fraud_types"]["ring_a"]
    result = graph_investigator.graph_investigator({"claim_id": ring_a[0]})
    assert calls == []
    assert [query_run["template"] for query_run in result["graph_queries_run"]] == [
        "nl_links_shared_phone", "nl_links_shared_address", "nl_links_clinic_and_attorney",
        "nl_links_firm_and_expert", "nl_repeat_claims", "nl_copied_story"]
    linked = {entry["claim_id"] for entry in result["linked_claims"]}
    assert len(linked & set(ring_a[1:])) >= 5                    # the ring is found through its links
    assert ring_a[0] not in linked                                # never linked to itself
    assert result["graph_warnings"] == []


def test_round_two_runs_only_allowed_templates(driver, truth, monkeypatch):
    answer = json.dumps({"templates": [
        {"name": "MATCH (n) DETACH DELETE n"}, {"name": "drop_database"}, "claims_sharing_clinic",
        {"name": "expand_linked_claims", "hops": 50}, {"name": "claims_sharing_phone"},
        {"name": "claims_sharing_phone"}]})
    fake_ask_llm, calls = fake_llm_answer(answer)
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    counts_before = count_graph(driver)

    result = graph_investigator.graph_investigator(dict(ROUND_TWO, claim_id=truth["fraud_types"]["ring_a"][0]))
    assert len(calls) == 1 and "Who else shares a clinic?" in calls[0]
    assert result["graph_templates_chosen"] == [{"name": "claims_sharing_phone"}]
    assert [query_run["template"] for query_run in result["graph_queries_run"]][-1] == "claims_sharing_phone"
    assert len(result["graph_warnings"]) == 4
    assert count_graph(driver) == counts_before          # nothing was changed or deleted


@pytest.mark.parametrize("bad_answer", ["not json at all", '{"templates": "all"}', '{"reason": "x"}',
                                        '{"templates": [{"name": "nothing_valid"}]}'])
def test_bad_llm_answer_in_round_two_falls_back_to_the_six_basic_templates(driver, truth, monkeypatch, bad_answer):
    fake_ask_llm, _ = fake_llm_answer(bad_answer)
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    result = graph_investigator.graph_investigator(dict(ROUND_TWO, claim_id=truth["demo_claims"]["ring"]))
    ran = [query_run["template"] for query_run in result["graph_queries_run"]]
    assert ran[-6:] == list(investigation.LINK_TEMPLATES)
    assert result["graph_warnings"]


def test_failed_llm_call_falls_back(driver, truth, monkeypatch):
    def failing_ask_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        raise RuntimeError("Simulated API failure")
    monkeypatch.setattr(graph_investigator, "ask_llm", failing_ask_llm)
    result = graph_investigator.graph_investigator(dict(ROUND_TWO, claim_id=truth["demo_claims"]["ring"]))
    assert [query_run["template"] for query_run in result["graph_queries_run"]][-6:] == \
        list(investigation.LINK_TEMPLATES)
    assert "Simulated API failure" in result["graph_warnings"][0]


def test_unknown_claim_gives_an_error_and_no_llm_call(driver, monkeypatch):
    fake_ask_llm, calls = fake_llm_answer("{}")
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    result = graph_investigator.graph_investigator(dict(ROUND_TWO, claim_id="C-9999"))
    assert result == {"error_message": "Claim C-9999 was not found in the graph."}
    assert calls == []


def test_json_inside_a_code_fence_is_read():
    answer = '```json\n{"templates": [{"name": "expand_linked_claims", "hops": 2}], "reason": "r"}\n```'
    choices, reason, warnings = graph_investigator.parse_template_choices(answer)
    assert choices == [{"name": "expand_linked_claims", "hops": 2}]
    assert reason == "r"
    assert warnings == []
