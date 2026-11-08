"""Step 5 tests: the query templates and the Graph Investigator agent.

Needs Neo4j running and data/tables. The expected links come straight from the
CSV files. A fake LLM replaces the real one, so these tests cost nothing.
"""

import csv
import json

import pytest

from src import config
from src.agents import graph_investigator
from src.graph import investigation
from src.graph.connection import open_neo4j_driver
from src.graph.loader import count_graph, load_graph

NEEDS_V1_DATA = "needs v1 data; replaced in V6 or V7, and V8 (network templates)"

# Ring A, Ring B, Ring C and a family claim: together they use every template.
TEST_CLAIM_IDS = ["C-1037", "C-1003", "C-1006", "C-1047"]


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
def driver():
    load_graph(config.TABLES_DIR)          # safe to repeat; makes sure the graph matches the CSV files
    neo4j_driver = open_neo4j_driver()
    yield neo4j_driver
    neo4j_driver.close()


def fake_llm_answer(answer_text):
    calls = []

    def fake_ask_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        calls.append(user_prompt)
        return answer_text
    return fake_ask_llm, calls


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_each_template_alone_matches_the_csv_files(driver):
    keys = shared_key_by_claim()
    for template_name, key_of_claim in keys.items():
        links_found_somewhere = 0
        for claim_id in TEST_CLAIM_IDS:
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


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_unknown_template_and_bad_hops_are_refused(driver):
    with pytest.raises(ValueError):
        investigation.run_link_template(driver, "MATCH (n) DETACH DELETE n", ["C-1037"])
    for bad_hops in [0, 4, True, "2", 2.0, None]:
        with pytest.raises(ValueError):
            investigation.expand_linked_claims(driver, "C-1037", bad_hops)


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_one_hop_expansion_equals_the_six_templates_together(driver):
    expected = set()
    for template_name in investigation.LINK_TEMPLATES:
        for link in investigation.run_link_template(driver, template_name, ["C-1037"]):
            expected.add(link["linked_claim_id"])
    one_hop = {link["linked_claim_id"] for link in investigation.expand_linked_claims(driver, "C-1037", 1)}
    two_hops = {link["linked_claim_id"] for link in investigation.expand_linked_claims(driver, "C-1037", 2)}
    assert one_hop == expected
    assert one_hop < two_hops                 # a proper subset: hop 2 adds claims
    assert "C-1037" not in two_hops           # the start claim is never "linked" to itself


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_ring_a_claim_finds_the_other_ring_a_claims(driver, monkeypatch):
    answer = json.dumps({"templates": [{"name": "claims_sharing_phone"}, {"name": "claims_sharing_address"},
                                       {"name": "claims_sharing_repair_shop"}], "reason": "test"})
    fake_ask_llm, _ = fake_llm_answer(answer)
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        ring_a_claim_ids = json.load(file)["rings"][0]["claim_ids"]

    result = graph_investigator.graph_investigator({"claim_id": ring_a_claim_ids[0]})
    linked_claim_ids = {entry["claim_id"] for entry in result["linked_claims"]}
    assert set(ring_a_claim_ids[1:]) <= linked_claim_ids
    assert result["graph_warnings"] == []


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_agent_runs_only_allowed_templates(driver, monkeypatch):
    answer = json.dumps({"templates": [
        {"name": "MATCH (n) DETACH DELETE n"}, {"name": "drop_database"}, "claims_sharing_clinic",
        {"name": "expand_linked_claims", "hops": 50}, {"name": "claims_sharing_phone"},
        {"name": "claims_sharing_phone"}]})
    fake_ask_llm, _ = fake_llm_answer(answer)
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    counts_before = count_graph(driver)

    result = graph_investigator.graph_investigator({"claim_id": "C-1037"})
    assert result["graph_templates_chosen"] == [{"name": "claims_sharing_phone"}]
    assert [query_run["template"] for query_run in result["graph_queries_run"]] == ["claims_sharing_phone"]
    assert len(result["graph_warnings"]) == 4
    assert count_graph(driver) == counts_before          # nothing was changed or deleted


@pytest.mark.skip(reason=NEEDS_V1_DATA)
@pytest.mark.parametrize("bad_answer", ["not json at all", '{"templates": "all"}', '{"reason": "x"}',
                                        '{"templates": [{"name": "nothing_valid"}]}'])
def test_bad_llm_answer_falls_back_to_the_six_basic_templates(driver, monkeypatch, bad_answer):
    fake_ask_llm, _ = fake_llm_answer(bad_answer)
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    result = graph_investigator.graph_investigator({"claim_id": "C-1037"})
    ran = [query_run["template"] for query_run in result["graph_queries_run"]]
    assert ran == list(investigation.LINK_TEMPLATES)
    assert result["graph_warnings"]


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_failed_llm_call_falls_back(driver, monkeypatch):
    def failing_ask_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        raise RuntimeError("Simulated API failure")
    monkeypatch.setattr(graph_investigator, "ask_llm", failing_ask_llm)
    result = graph_investigator.graph_investigator({"claim_id": "C-1037"})
    assert len(result["graph_queries_run"]) == len(investigation.LINK_TEMPLATES)
    assert "Simulated API failure" in result["graph_warnings"][0]


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_unknown_claim_gives_an_error_and_no_llm_call(driver, monkeypatch):
    fake_ask_llm, calls = fake_llm_answer("{}")
    monkeypatch.setattr(graph_investigator, "ask_llm", fake_ask_llm)
    result = graph_investigator.graph_investigator({"claim_id": "C-9999"})
    assert result == {"error_message": "Claim C-9999 was not found in the graph."}
    assert calls == []


def test_json_inside_a_code_fence_is_read():
    answer = '```json\n{"templates": [{"name": "expand_linked_claims", "hops": 2}], "reason": "r"}\n```'
    choices, reason, warnings = graph_investigator.parse_template_choices(answer)
    assert choices == [{"name": "expand_linked_claims", "hops": 2}]
    assert reason == "r"
    assert warnings == []
