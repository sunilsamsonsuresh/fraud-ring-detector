"""Step 9 tests: the supervisor rules, the loop limit, and the Challenger's checks.

The workflow tests replace every agent with a small fake, so they need no LLM and no Neo4j.
"""

import json

import pytest
from langgraph.graph import END

from src import config, workflow
from src.agents import challenger
from src.agents.report_writer import make_summary_line


@pytest.fixture
def fake_agents(monkeypatch):
    """Replace every node with a fake that records its name. Returns the list of calls."""
    calls = []

    def fake(name, result):
        def agent(state):
            calls.append(name)
            return result
        return agent

    monkeypatch.setattr(workflow, "intake", fake("intake", {"documents_read": 1}))
    monkeypatch.setattr(workflow, "graph_investigator", fake("graph_investigator", {"linked_claims": []}))
    monkeypatch.setattr(workflow, "evidence", fake("evidence", {"copied_text": []}))
    monkeypatch.setattr(workflow, "litigation_analyst", fake("litigation_analyst", {}))
    monkeypatch.setattr(workflow, "risk_scoring", fake("risk_scoring", {"risk_score": 50}))
    monkeypatch.setattr(workflow, "report_writer", fake("report_writer", {"report_text": "report"}))
    monkeypatch.setattr(workflow, "save_result", fake("save_result", {"saved_summary": "summary"}))
    monkeypatch.setattr(workflow, "count_lawsuits", lambda claim_ids: 0)
    return calls


def set_challenger(monkeypatch, calls, needs_more_evidence):
    def fake_challenger(state):
        calls.append("challenger")
        return {"challenger_review": {"needs_more_evidence": needs_more_evidence, "follow_up_question": "?"}}
    monkeypatch.setattr(workflow, "challenger", fake_challenger)


def test_loop_stops_after_two_rounds_back(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=True)   # always asks for more
    final_state = workflow.investigate_claim("C-1037")
    assert config.MAX_INVESTIGATION_LOOPS == 2
    assert final_state["loop_count"] == 2
    assert fake_agents.count("challenger") == 3          # first round + 2 rounds back
    assert fake_agents.count("graph_investigator") == 3
    assert fake_agents.count("intake") == 1              # the PDFs are read once, not on every round
    assert fake_agents[-2:] == ["report_writer", "save_result"]


def test_no_loop_when_the_challenger_is_satisfied(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=False)
    final_state = workflow.investigate_claim("C-1037")
    assert final_state["loop_count"] == 0
    assert fake_agents == ["intake", "graph_investigator", "evidence", "risk_scoring", "challenger",
                           "report_writer", "save_result"]


def test_litigation_analyst_runs_only_when_a_lawsuit_exists(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=False)
    monkeypatch.setattr(workflow, "count_lawsuits", lambda claim_ids: 1)
    workflow.investigate_claim("C-1143")
    assert fake_agents.index("litigation_analyst") == fake_agents.index("evidence") + 1


def test_an_error_ends_the_run(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=False)
    monkeypatch.setattr(workflow, "graph_investigator",
                        lambda state: {"error_message": "Claim C-9999 was not found in the graph."})
    final_state = workflow.investigate_claim("C-9999")
    assert final_state["error_message"].startswith("Claim C-9999")
    assert "report_writer" not in fake_agents and "save_result" not in fake_agents


def test_challenger_accepts_only_signal_names_with_points():
    answer = json.dumps({
        "innocent_explanations": [
            {"signal": "shared_phone", "explanation": "Same family.", "based_on": "same policy"},
            {"signal": "shared_phone", "explanation": "Repeated.", "based_on": ""},
            {"signal": "risk_score", "explanation": "Not a signal.", "based_on": ""},
            {"signal": "copied_text", "explanation": "No points for this signal.", "based_on": ""}],
        "needs_more_evidence": "true", "follow_up_question": "Who else?"})
    review, warnings = challenger.parse_challenge(answer, ["shared_phone", "shared_address"])
    assert [item["signal"] for item in review["innocent_explanations"]] == ["shared_phone"]
    assert review["needs_more_evidence"] is False      # the text "true" is not a real JSON true
    assert len(warnings) == 3
    bad_review, bad_warnings = challenger.parse_challenge("not json", ["shared_phone"])
    assert bad_review["innocent_explanations"] == [] and bad_review["needs_more_evidence"] is False
    assert bad_warnings


def test_household_rule_rejects_innocent_reasons_for_unrelated_people():
    signals = [{"name": "copied_text", "points": 25, "evidence": [{"claim_id": "C-1102"}, {"claim_id": "C-1209"}]},
               {"name": "shared_phone", "points": 5, "evidence": [{"claim_id": "C-1209"}]},
               {"name": "shared_clinic", "points": 5, "evidence": [{"claim_id": "C-1102"}]}]
    family = {"same_policy": True, "same_last_name": True, "same_vehicle": True}
    stranger = {"same_policy": False, "same_last_name": False, "same_vehicle": False}
    explanations = [{"signal": "copied_text"}, {"signal": "shared_phone"}, {"signal": "shared_clinic"}]
    kept, warnings = challenger.check_household_rule(explanations, signals,
                                                     {"C-1102": stranger, "C-1209": family})
    assert [item["signal"] for item in kept] == ["shared_phone", "shared_clinic"]   # clinic: no household rule
    assert warnings == ["Rejected the Challenger's innocent explanation for copied_text: C-1102 not the same household."]


def test_summary_line_is_fixed_by_plain_code():
    state = {"final_risk_level": "high", "final_risk_score": 65,
             "risk_signals": [{"name": "shared_clinic", "points": 5}, {"name": "copied_text", "points": 25},
                              {"name": "shared_phone", "points": 15}, {"name": "shared_address", "points": 15}]}
    assert make_summary_line(state) == ("high risk (65/100). Top signals: copied_text, shared_address, "
                                        "shared_phone. Needs human review.")
