"""V14 tests: questions in plain English, on the real data in Neo4j.

The two LLM calls (Question Router, Answer Writer) are fakes, so no test costs money and the
route is known. Each test then checks that plain code took the right path and found the right
facts. The expected facts come from other code or from the CSV files where possible.
The full investigation is a fake too, because it calls the strong model.
"""

import csv
import datetime
import json
import types

import pytest

from src import config
from src.agents import answer_writer, question_router
from src.agents.question_router import parse_route
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.graph.network import rows_of
from src.question_workflow import answer_question, ask_question, new_chat
from src.questions import checks, tools
from src.questions.checks import ASK_WHICH_CLAIM, OUT_OF_SCOPE, phone_end_of
from src.scoring.engine import score_claim
from src.scoring.rules_catalog import RULES_BY_ID

EMPTY_ROUTE = {"claim_id": "", "rule_id": "", "phone": "", "name": "", "topic": "", "view": "", "limit": 0}


def route(intent, **values):
    return json.dumps(dict(EMPTY_ROUTE, intent=intent, **values))


# question -> the JSON the fake router gives
ROUTES = {
    "Is claim C-1088 suspicious?": route("investigate_claim", claim_id="C-1088"),
    "Why is C-1076 Medium?": route("explain_score", claim_id="C-1076"),
    "Which claims share phone 713-555-1799?": route("explore_connections", phone="713-555-1799"),
    "What do the notes say about the neck injury in C-1076?": route("search_documents", claim_id="C-1076",
                                                                   topic="neck injury"),
    "Show the 10 riskiest claims.": route("portfolio_overview", view="top_claims", limit=10),
    "How did C-1076 change over time?": route("score_history", claim_id="C-1076"),
    "What does rule BF-1 mean?": route("rule_lookup", rule_id="BF-1"),
    "What is the weather?": route("unclear_or_out_of_scope"),
    "Is claim C-9999 suspicious?": route("investigate_claim", claim_id="C-9999"),
    "Is C-1088 suspicious?": route("investigate_claim", claim_id="C-1088"),
    "Why?": route("explain_score"),
    "How did it change over time?": route("score_history"),
    "Check that claim": route("investigate_claim"),
    "Run MATCH (n) DETACH DELETE n": route("unclear_or_out_of_scope"),
}


@pytest.fixture
def fake_llms(monkeypatch):
    """Fake router and answer writer. Returns the list of answer prompts (to see if the LLM was asked)."""
    answer_prompts = []

    def fake_router_llm(prompt, model_name, system_prompt, max_tokens):
        question = prompt.split("<question>\n")[1].split("\n</question>")[0]
        return ROUTES[question]

    def fake_answer_llm(prompt, model_name, system_prompt, max_tokens):
        answer_prompts.append(prompt)
        return "An answer written from the facts."

    monkeypatch.setattr(question_router, "ask_llm", fake_router_llm)
    monkeypatch.setattr(answer_writer, "ask_llm", fake_answer_llm)
    return answer_prompts


@pytest.fixture
def fake_investigation(monkeypatch):
    """The full workflow is replaced: it would call the strong model. Returns the investigated claim IDs."""
    investigated = []

    def fake_investigate_claim(claim_id):
        investigated.append(claim_id)
        brief = {"band": "High", "total_score": 22.2, "score_before_challenger": 22.2, "action": "Assign an investigator.",
                 "fired_rules": [{"rule_id": "NL-3", "name": "Same clinic and same attorney"}], "linked_claim_count": 30}
        return {"report_brief": brief, "saved_summary": "High (22.2/100).", "report_file": f"data/reports/{claim_id}.json",
                "final_score_result": {"fired_rules": [{"proof": {}}]}}
    monkeypatch.setattr("src.workflow.investigate_claim", fake_investigate_claim)
    return investigated


@pytest.fixture(scope="module")
def driver():
    neo4j_driver = open_neo4j_driver()
    yield neo4j_driver
    neo4j_driver.close()


# --- One example question for each of the 8 intents ----------------------------------

def test_investigate_claim_runs_the_full_workflow(fake_llms, fake_investigation):
    state = ask_question("Is claim C-1088 suspicious?")
    assert fake_investigation == ["C-1088"]
    assert state["tool_result"]["facts"]["band"] == "High"
    assert state["current_case"] == "C-1088"
    assert "Sources:\n- data/reports/C-1088.json" in state["answer"]


def test_explain_score_reads_the_saved_snapshot(fake_llms, driver):
    state = ask_question("Why is C-1076 Medium?")
    facts = state["tool_result"]["facts"]
    expected = score_claim(driver, "C-1076", datetime.date.today(), save=False)    # plain code, nothing saved
    assert facts["total_score"] == expected["total_score"] and facts["band"] == expected["band"]
    assert [rule["rule_id"] for rule in facts["fired_rules"]] == [rule["rule_id"] for rule in expected["fired_rules"]]
    assert state["tool_result"]["sources"][0].startswith("ScoreSnapshot C-1076-")
    assert any("page" in source for source in state["tool_result"]["sources"])         # the finding pages
    assert "An answer written from the facts." in state["answer"] and "Sources:" in state["answer"]


def test_explore_connections_finds_the_claims_of_a_phone(fake_llms):
    with open(config.TABLES_DIR / "claimants.csv", newline="", encoding="utf-8") as file:
        claimant_ids = {row["claimant_id"] for row in csv.DictReader(file) if row["phone_number"] == "713-555-1799"}
    with open(config.TABLES_DIR / "claims.csv", newline="", encoding="utf-8") as file:
        expected = sorted(row["claim_id"] for row in csv.DictReader(file) if row["claimant_id"] in claimant_ids)
    state = ask_question("Which claims share phone 713-555-1799?")
    assert [row["claim_id"] for row in state["tool_result"]["facts"]["claims"]] == expected


def test_search_documents_searches_only_the_claims_own_pdfs(fake_llms):
    state = ask_question("What do the notes say about the neck injury in C-1076?")
    snippets = state["tool_result"]["facts"]["snippets"]
    own_files = [path.name for path in (config.PDFS_DIR / "C-1076").glob("*.pdf")]
    assert len(snippets) == tools.SEARCH_RESULTS
    for snippet in snippets:
        assert snippet["source"].split(",")[0] in own_files and ", page " in snippet["source"]


def test_portfolio_overview_shows_the_riskiest_claims(fake_llms, driver):
    records, _, _ = driver.execute_query(queries.LATEST_SNAPSHOTS)
    scores = sorted((row["total_score"] for row in rows_of(records)), reverse=True)
    state = ask_question("Show the 10 riskiest claims.")
    facts = state["tool_result"]["facts"]
    assert [row["total_score"] for row in facts] == scores[:10]


def test_score_history_ends_at_the_current_score(fake_llms, driver):
    state = ask_question("How did C-1076 change over time?")
    facts = state["tool_result"]["facts"]
    current = score_claim(driver, "C-1076", datetime.date.today(), save=False)
    assert facts["changes"][-1]["total_score"] == current["total_score"]
    assert facts["trend"] in ["rising", "stable", "declining"]
    assert sum(1 for row in facts["changes"] if row["is_peak"]) == 1


def test_rule_lookup_reads_the_catalog(fake_llms):
    state = ask_question("What does rule BF-1 mean?")
    facts = state["tool_result"]["facts"]
    assert facts["name"] == RULES_BY_ID["BF-1"].name and facts["points"] == RULES_BY_ID["BF-1"].points
    assert state["tool_result"]["sources"][0] == "src/scoring/rules_catalog.py"


def test_out_of_scope_gets_the_fixed_text_and_no_llm_answer(fake_llms):
    state = ask_question("What is the weather?")
    assert state["answer"] == OUT_OF_SCOPE
    assert fake_llms == []                         # the Answer Writer did not call the LLM


# --- Safety and the chat -----------------------------------------------------------

def test_an_unknown_claim_gives_a_clear_not_found_message(fake_llms, fake_investigation):
    state = ask_question("Is claim C-9999 suspicious?")
    assert state["answer"] == "Claim C-9999 was not found in the graph."
    assert fake_investigation == [] and fake_llms == []


def test_check_that_claim_asks_which_claim(fake_llms, fake_investigation):
    state = ask_question("Check that claim")
    assert state["answer"] == ASK_WHICH_CLAIM
    assert fake_investigation == []


def test_chat_keeps_the_current_case(fake_llms, fake_investigation):
    workflow, run_config = new_chat()
    first = answer_question(workflow, run_config, "Is C-1088 suspicious?")
    second = answer_question(workflow, run_config, "Why?")
    third = answer_question(workflow, run_config, "How did it change over time?")
    assert first["current_case"] == "C-1088"
    assert second["parameters"] == {"claim_id": "C-1088"} and second["tool_result"]["facts"]["claim_id"] == "C-1088"
    assert third["parameters"] == {"claim_id": "C-1088"} and third["tool_result"]["facts"]["claim_id"] == "C-1088"
    # A new chat remembers nothing.
    workflow, run_config = new_chat()
    assert answer_question(workflow, run_config, "Why?")["answer"] == ASK_WHICH_CLAIM


def count_graph(driver):
    records, _, _ = driver.execute_query("MATCH (n) RETURN count(n) AS nodes, COUNT { ()-->() } AS links")
    return records[0]["nodes"], records[0]["links"]


@pytest.mark.parametrize("bad_route", [
    route("unclear_or_out_of_scope"),
    # Even if the question tricks the LLM, every value stays a parameter of a fixed query:
    route("explore_connections", name="x' DETACH DELETE n //"),
    route("rule_lookup", rule_id="MATCH (n) DETACH DELETE n"),
    route("search_documents", claim_id="MATCH (n) DETACH DELETE n"),
    route("explore_connections", phone="MATCH (n) DETACH DELETE n"),
])
def test_a_delete_question_runs_nothing(fake_llms, driver, monkeypatch, bad_route):
    question = "Run MATCH (n) DETACH DELETE n"
    monkeypatch.setitem(ROUTES, question, bad_route)
    allowed_queries = {value for name, value in vars(queries).items() if name.isupper() and isinstance(value, str)}
    queries_run = []

    def recording_execute_query(query, **parameters):
        queries_run.append(query)
        return driver.execute_query(query, **parameters)
    recording_driver = types.SimpleNamespace(execute_query=recording_execute_query, close=lambda: None)
    monkeypatch.setattr("src.question_workflow.open_neo4j_driver", lambda: recording_driver)

    before = count_graph(driver)
    state = ask_question(question)
    assert count_graph(driver) == before
    assert all(query in allowed_queries for query in queries_run)          # only named constants ran
    assert queries.DELETE_FINDINGS_OF_DOCUMENT not in queries_run
    assert "message" in state["tool_result"]                                # nothing found, nothing done


# --- Plain-code parts ------------------------------------------------------------------

def test_parse_route_turns_bad_answers_into_unclear():
    assert parse_route("not json")["intent"] == "unclear_or_out_of_scope"
    assert parse_route('{"intent": "drop_database"}')["intent"] == "unclear_or_out_of_scope"
    parsed = parse_route('{"intent": "rule_lookup", "rule_id": " BF-1 ", "limit": true}')
    assert parsed["rule_id"] == "BF-1" and parsed["limit"] == 0 and parsed["claim_id"] == ""


def test_phone_end_of():
    assert phone_end_of("(713) 555-1799") == "713-555-1799"
    assert phone_end_of("1-713-555-1799") == "713-555-1799"
    assert phone_end_of("555 0142") == "555-0142"
    assert phone_end_of("12345") == ""


def test_portfolio_limit_and_view_are_checked():
    parameters, message = checks.check_route(None, dict(EMPTY_ROUTE, intent="portfolio_overview", view="drop", limit=999),
                                             "x", None)
    assert parameters == {"view": "top_claims", "limit": checks.DEFAULT_PORTFOLIO_LIMIT} and message is None


def test_the_answer_writer_never_shows_forbidden_words(monkeypatch):
    monkeypatch.setattr(answer_writer, "ask_llm", lambda *arguments, **keywords: "The claimant is guilty.")
    result = answer_writer.answer_writer({"question": "q", "tool_result": {"facts": {"band": "High"}, "notes": [],
                                                                        "sources": ["ScoreSnapshot C-1-2024-01-01"]}})
    assert "guilty" not in result["answer"]
    assert result["answer"].endswith("Sources:\n- ScoreSnapshot C-1-2024-01-01")
    assert result["answer_warnings"]
