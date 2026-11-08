"""The investigation workflow: LangGraph plus plain supervisor rules (PLAN.md, A6 and Step 9).

LangGraph runs one agent (a "node"), merges the dict it returns into the state, then
asks choose_next_agent which node runs next. choose_next_agent is plain if/else code.
No LLM decides the route.

Intake -> Graph Investigator -> Evidence
       -> Litigation Analyst (only if this claim or a linked claim has a lawsuit)
       -> Risk Scoring -> Challenger
       -> if the Challenger needs more evidence and loop_count < MAX_INVESTIGATION_LOOPS:
              start_next_round -> back to Graph Investigator
       -> else Report Writer -> save_result -> end
Any agent that sets error_message ends the run.
"""

import datetime
from functools import partial

from langgraph.graph import END, START, StateGraph

from src import config
from src.agents.challenger import challenger
from src.agents.evidence import evidence
from src.agents.graph_investigator import graph_investigator
from src.agents.intake import intake
from src.agents.litigation_analyst import count_lawsuits, litigation_analyst
from src.agents.report_writer import make_summary_line, report_writer
from src.agents.risk_scoring import risk_scoring
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.state import InvestigationState

# Each step of a run counts against LangGraph's recursion limit. One round is about 6 steps,
# and we allow 1 + MAX_INVESTIGATION_LOOPS rounds, so 50 is far more than a normal run needs.
RECURSION_LIMIT = 50


def start_next_round(state):
    """Count the loop before going back to the Graph Investigator."""
    return {"loop_count": state.get("loop_count", 0) + 1}


def save_result(state):
    """Save the score, the date and a one-line summary on the Claim node, and the report as a file."""
    summary = make_summary_line(state)
    driver = open_neo4j_driver()
    try:
        driver.execute_query(queries.SAVE_INVESTIGATION_RESULT, claim_id=state["claim_id"],
                             risk_score=state["final_risk_score"], summary=summary,
                             investigated_on=datetime.date.today().isoformat())
    finally:
        driver.close()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = config.REPORTS_DIR / f"{state['claim_id']}.md"
    report_file.write_text(state["report_text"], encoding="utf-8")
    return {"saved_summary": summary, "report_file": str(report_file)}


def choose_next_agent(finished_agent, state):
    """The supervisor rules (PLAN.md, A6). Returns the name of the next node, or END."""
    if state.get("error_message"):
        return END
    if finished_agent == "intake":
        return "graph_investigator"
    if finished_agent == "graph_investigator":
        return "evidence"
    if finished_agent == "evidence":
        claim_ids = [state["claim_id"]]
        for entry in state.get("linked_claims", []):
            claim_ids.append(entry["claim_id"])
        if count_lawsuits(claim_ids) > 0:
            return "litigation_analyst"
        return "risk_scoring"
    if finished_agent == "litigation_analyst":
        return "risk_scoring"
    if finished_agent == "risk_scoring":
        return "challenger"
    if finished_agent == "challenger":
        needs_more_evidence = state["challenger_review"]["needs_more_evidence"]
        if needs_more_evidence and state.get("loop_count", 0) < config.MAX_INVESTIGATION_LOOPS:
            return "start_next_round"
        return "report_writer"
    if finished_agent == "start_next_round":
        return "graph_investigator"
    if finished_agent == "report_writer":
        return "save_result"
    return END


def build_workflow():
    """Build and compile the LangGraph graph. Agents are looked up here, when the graph is built."""
    nodes = {
        "intake": intake, "graph_investigator": graph_investigator, "evidence": evidence,
        "litigation_analyst": litigation_analyst, "risk_scoring": risk_scoring, "challenger": challenger,
        "start_next_round": start_next_round, "report_writer": report_writer, "save_result": save_result,
    }
    graph = StateGraph(InvestigationState)
    for name, function in nodes.items():
        graph.add_node(name, function)
        # partial(choose_next_agent, name) = a function that calls choose_next_agent(name, state).
        graph.add_conditional_edges(name, partial(choose_next_agent, name))
    graph.add_edge(START, "intake")
    return graph.compile()


def investigate_claim(claim_id):
    """Run the whole investigation on one claim. Return the final state."""
    workflow = build_workflow()
    return workflow.invoke({"claim_id": claim_id, "loop_count": 0}, {"recursion_limit": RECURSION_LIMIT})
