"""V13 tests: the run pauses for the investigator, and each answer does the right thing.

Every agent is a small fake, so these tests need no LLM and no Neo4j. The Human approval
node is the real one. Decisions go to a temporary file, not to data/decisions.jsonl.
"""

import json

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from src import config, workflow
from src.agents.human_approval import check_answer


@pytest.fixture
def fake_run(monkeypatch, tmp_path):
    """Fake agents. Returns a dict: the list of calls, and the states the Graph Investigator saw."""
    record = {"calls": [], "graph_states": []}
    monkeypatch.setattr(config, "DECISIONS_FILE", tmp_path / "decisions.jsonl")

    def fake(name, result):
        def agent(state):
            record["calls"].append(name)
            return result
        return agent

    def fake_graph_investigator(state):
        record["calls"].append("graph_investigator")
        record["graph_states"].append(dict(state))
        return {"linked_claims": []}

    monkeypatch.setattr(workflow, "intake", fake("intake", {"intake_skipped": True}))
    monkeypatch.setattr(workflow, "graph_investigator", fake_graph_investigator)
    monkeypatch.setattr(workflow, "evidence", fake("evidence", {}))
    monkeypatch.setattr(workflow, "risk_scoring", fake("risk_scoring", {"risk_score": 22.2}))
    monkeypatch.setattr(workflow, "challenger", fake("challenger", {
        "challenger_review": {"needs_more_evidence": False}, "final_risk_score": 22.2, "final_risk_level": "High"}))
    monkeypatch.setattr(workflow, "report_writer", fake("report_writer", {"report_text": "# Referral brief: claim C-1088"}))
    monkeypatch.setattr(workflow, "save_result", fake("save_result", {"saved_summary": "s", "report_file": "f"}))
    monkeypatch.setattr(workflow, "count_lawsuits", lambda claim_ids: 0)
    return record


def answers_in_order(*answers):
    """A fake investigator: gives the answers one by one and keeps every pause it saw."""
    pauses = []

    def get_human_answer(pause_value):
        pauses.append(pause_value)
        return answers[len(pauses) - 1]
    return get_human_answer, pauses


def saved_decisions():
    if not config.DECISIONS_FILE.exists():
        return []
    return [json.loads(line) for line in config.DECISIONS_FILE.read_text(encoding="utf-8").splitlines()]


def test_the_run_stops_and_waits(fake_run):
    graph = workflow.build_workflow(InMemorySaver())
    run_config = {"configurable": {"thread_id": "test-pause"}}
    state = graph.invoke({"claim_id": "C-1088", "loop_count": 0, "approval_wanted": True}, run_config)
    pause = state["__interrupt__"][0].value
    assert pause["claim_id"] == "C-1088" and pause["band"] == "High" and pause["total_score"] == 22.2
    assert pause["report_text"].startswith("# Referral brief")
    assert pause["allowed_decisions"] == ["approve", "reject", "more"]
    assert graph.get_state(run_config).next == ("human_approval",)     # waiting at the approval node
    assert fake_run["calls"][-1] == "save_result"
    assert saved_decisions() == []                                      # nothing is decided yet


def test_approve_ends_the_run_and_saves_the_decision(fake_run):
    get_human_answer, pauses = answers_in_order({"decision": "approve", "reason": ""})
    state = workflow.investigate_claim("C-1088", get_human_answer)
    assert len(pauses) == 1 and state["human_decision"] == "approve"
    assert fake_run["calls"].count("graph_investigator") == 1
    decisions = saved_decisions()
    assert len(decisions) == 1
    assert decisions[0]["claim_id"] == "C-1088" and decisions[0]["band"] == "High"
    assert decisions[0]["decision"] == "approve" and decisions[0]["decided_on"]
    assert set(decisions[0]) == {"claim_id", "band", "total_score", "decision", "reason", "decided_on", "round"}


def test_reject_ends_the_run_and_saves_the_reason(fake_run):
    get_human_answer, pauses = answers_in_order({"decision": "Reject", "reason": "  Same household, known family. "})
    state = workflow.investigate_claim("C-1088", get_human_answer)
    assert state["human_decision"] == "reject" and len(pauses) == 1
    assert fake_run["calls"].count("report_writer") == 1               # no new round
    assert saved_decisions()[0]["reason"] == "Same household, known family."


def test_more_runs_one_more_round_and_then_asks_again(fake_run):
    get_human_answer, pauses = answers_in_order({"decision": "more", "reason": "Check the other claims of the clinic."},
                                                {"decision": "approve", "reason": ""})
    state = workflow.investigate_claim("C-1088", get_human_answer)
    assert len(pauses) == 2
    assert fake_run["calls"].count("graph_investigator") == 2 and fake_run["calls"].count("report_writer") == 2
    assert fake_run["calls"].count("intake") == 1                        # the PDFs are not read again
    second_round = fake_run["graph_states"][1]
    assert second_round["loop_count"] == 1
    assert second_round["investigator_request"] == "Check the other claims of the clinic."
    assert pauses[1]["allowed_decisions"] == ["approve", "reject"]      # "more" only once (MAX_HUMAN_REQUESTS)
    assert [item["decision"] for item in saved_decisions()] == ["more", "approve"]
    assert [item["round"] for item in saved_decisions()] == [1, 2]
    assert state["human_decision"] == "approve"


def test_check_answer_refuses_bad_answers():
    allowed = ["approve", "reject", "more"]
    assert check_answer({"decision": "approve", "reason": ""}, allowed)[0] == "approve"
    assert check_answer({"decision": "reject", "reason": ""}, allowed)[2] == "The decision 'reject' needs a reason."
    assert check_answer({"decision": "more", "reason": ""}, allowed)[2] is not None
    assert check_answer({"decision": "delete everything", "reason": "x"}, allowed)[2].startswith("The decision")
    assert check_answer({"decision": "more", "reason": "x"}, ["approve", "reject"])[2] is not None
    assert check_answer("approve", allowed)[2] == "The answer is not a dict."


def test_a_bad_answer_saves_nothing_and_ends_the_run(fake_run):
    get_human_answer, _ = answers_in_order({"decision": "maybe", "reason": ""})
    state = workflow.investigate_claim("C-1088", get_human_answer)
    assert state["error_message"].startswith("No decision was saved.")
    assert saved_decisions() == []


def test_without_an_answer_function_the_run_does_not_pause(fake_run):
    state = workflow.investigate_claim("C-1088")
    assert "__interrupt__" not in state and "human_decision" not in state
    assert fake_run["calls"][-1] == "save_result"
