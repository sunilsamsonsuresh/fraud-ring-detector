"""Step 9 and V12 tests: the supervisor rules and the loop limit, the summary line and the brief.

The workflow tests replace every agent with a small fake, so they need no LLM and no Neo4j.
"""

import pytest
from langgraph.graph import END

from src import config, workflow
from src.agents.report_writer import make_summary_line
from src.reports.referral_brief import CLOSING_SENTENCE, brief_markdown, build_brief


@pytest.fixture
def fake_agents(monkeypatch):
    """Replace every node with a fake that records its name. Returns the list of calls."""
    calls = []

    def fake(name, result):
        def agent(state):
            calls.append(name)
            return result
        return agent

    monkeypatch.setattr(workflow, "intake", fake("intake", {"intake_skipped": True}))
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


def test_the_loop_stops_after_two_rounds(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=True)   # always asks for more
    final_state = workflow.investigate_claim("C-1026")
    assert config.MAX_INVESTIGATION_LOOPS == 1
    assert final_state["loop_count"] == 1
    assert fake_agents.count("challenger") == 2          # round 1 + round 2, never a third
    assert fake_agents.count("graph_investigator") == 2
    assert fake_agents.count("intake") == 1              # the PDFs are read once, not on every round
    assert fake_agents[-2:] == ["report_writer", "save_result"]


def test_no_loop_when_the_challenger_is_satisfied(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=False)
    final_state = workflow.investigate_claim("C-1026")
    assert final_state["loop_count"] == 0
    assert fake_agents == ["intake", "graph_investigator", "evidence", "risk_scoring", "challenger",
                           "report_writer", "save_result"]


def test_litigation_analyst_runs_only_in_round_one_for_the_claims_own_lawsuit(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=True)
    asked = []

    def count_lawsuits(claim_ids):
        asked.append(claim_ids)
        return 1
    monkeypatch.setattr(workflow, "count_lawsuits", count_lawsuits)
    workflow.investigate_claim("C-1016")
    assert fake_agents.count("litigation_analyst") == 1
    assert fake_agents.index("litigation_analyst") == fake_agents.index("evidence") + 1
    assert asked == [["C-1016"]]                         # only this claim's own lawsuit counts (A8)


def test_an_error_ends_the_run(fake_agents, monkeypatch):
    set_challenger(monkeypatch, fake_agents, needs_more_evidence=False)
    monkeypatch.setattr(workflow, "graph_investigator",
                        lambda state: {"error_message": "Claim C-9999 was not found in the graph."})
    final_state = workflow.investigate_claim("C-9999")
    assert final_state["error_message"].startswith("Claim C-9999")
    assert "report_writer" not in fake_agents and "save_result" not in fake_agents


def test_supervisor_rules_are_plain_if_else():
    assert workflow.choose_next_agent("intake", {}) == "graph_investigator"
    assert workflow.choose_next_agent("challenger", {"loop_count": 1, "challenger_review":
                                                      {"needs_more_evidence": True}}) == "report_writer"
    assert workflow.choose_next_agent("save_result", {}) == END
    assert workflow.choose_next_agent("risk_scoring", {"error_message": "x"}) == END


# --- The summary line and the brief (plain code) ------------------------------------

def made_up_result(total, band, fired):
    return {"total_score": total, "band": band, "action": "Assign an investigator.",
            "category_scores": {"BI": 0.0, "AS": 20.0, "BF": 0.0, "CT": 0.0, "NL": 50.0}, "coverage_pct": 55.0,
            "fired_rules": fired, "weak_findings": [{"feature": "x"}],
            "rule_results": {"BI-5": {"status": "not_evaluated", "proof": {"missing": "no attorney on the claim"}},
                             "AS-6": {"status": "fired", "proof": {}}}}


FIRED = [{"rule_id": "AS-6", "name": "More claimants than occupants", "points": 15, "points_in_total": 3.95,
          "proof": {"claimants_in_incident": 3, "findings": [
              {"finding_id": "F-1", "value": 2, "confidence": "High", "document_id": "C-1-police_report",
               "page_number": 1, "quote": "Driver Ann Lee"}]}},
         {"rule_id": "NL-4", "name": "Copied story", "points": 14, "points_in_total": 4.24,
          "proof": {"other_claims": ["C-2"]}}]


def test_summary_line_is_fixed_by_plain_code():
    state = {"final_score_result": made_up_result(21.0, "High", FIRED)}
    assert make_summary_line(state) == "High (21.0/100). Top rules: NL-4, AS-6. Possible link, needs human review."


def test_brief_has_every_section_and_its_sources():
    state = {"claim_id": "C-1", "loop_count": 1, "final_score_result": made_up_result(21.0, "High", FIRED),
             "score_result": made_up_result(23.4, "High", FIRED),
             "linked_claims": [{"claim_id": "C-2", "hop": 1, "links": [{"template": "nl_copied_story",
                                                                        "shared_value": "copied text in fnol",
                                                                        "via_claim_id": "C-1"}]},
                               {"claim_id": "C-4", "hop": 2, "links": [{"template": "nl_links_shared_phone",
                                                                        "shared_value": "713-555-0000",
                                                                        "via_claim_id": "C-2"}]}],
             "challenges": [{"check": "family link", "rules": ["NL-1"], "detail": ["C-3"],
                             "effect": "NL-1 does not count for links to family members.", "explanation": "Same home."}],
             "rule_quotes": [{"rule_id": "AS-6", "source": "C-1-police_report, page 1", "quote": "Driver Ann Lee"}]}
    brief = build_brief(state, history=[])
    assert brief["band"] == "High" and brief["action"] and brief["rounds"] == 2
    assert brief["fired_rules"][0]["sources"] == ["C-1-police_report, page 1"]
    assert brief["network"] == [{"claim_id": "C-2", "hop": 1, "why": ["nl_copied_story = copied text in fnol"]},
                                {"claim_id": "C-4", "hop": 2, "why": ["nl_links_shared_phone = 713-555-0000 (via C-2)"]}]
    assert "BI-5 Attorney before first treatment: no attorney on the claim" in brief["missing"]
    assert "Coverage 55.0%: not fully examined." in brief["missing"]
    text = brief_markdown(brief)
    for heading in ["# Referral brief: claim C-1", "## Fired rules with proof", "## Network picture",
                    "## Challenger notes", "## What is missing", CLOSING_SENTENCE]:
        assert heading in text
    assert "possible link, needs human review" in text.lower()
