"""The investigation workflow: LangGraph plus plain supervisor rules (PLAN-v2.md A8, V12).

LangGraph runs one agent (a "node"), merges the dict it returns into the state, then
asks choose_next_agent which node runs next. choose_next_agent is plain if/else code.
No LLM decides the route.

Intake (skips itself when the claim is already read)
  -> Graph Investigator -> Evidence
  -> Litigation Analyst (only in round 1, and only if this claim has a lawsuit)
  -> Risk Scoring -> Challenger
  -> if the Challenger asks for more evidence and loop_count < MAX_INVESTIGATION_LOOPS (1):
         start_next_round -> Graph Investigator (round 2) -> Evidence -> Risk Scoring -> Challenger
  -> else Report Writer -> save_result
  -> Human approval (V13; only when the caller gives a way to answer): the run pauses.
     approve or reject -> end.  more -> start_next_round -> Graph Investigator -> ... -> Human approval again
     (the investigator may ask for more MAX_HUMAN_REQUESTS times).
The Challenger can add at most 1 round. Any agent that sets error_message ends the run.

Pause and resume (V13): interrupt() needs a checkpointer, which keeps the state of a paused run.
InMemorySaver keeps it in memory, so a paused run lives only as long as this Python process.
A thread ID names one run inside the checkpointer.
"""

import datetime
import json
import uuid
from functools import partial

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from src import config
from src.agents.challenger import challenger
from src.agents.evidence import evidence
from src.agents.graph_investigator import graph_investigator
from src.agents.human_approval import human_approval
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
    """Save risk_score, band, last_investigated and summary on the Claim node, and the brief as
    data/reports/<claim>.json (a later web page reads this file)."""
    summary = make_summary_line(state)
    driver = open_neo4j_driver()
    try:
        driver.execute_query(queries.SAVE_INVESTIGATION_RESULT, claim_id=state["claim_id"],
                             risk_score=state["final_risk_score"], band=state["final_risk_level"], summary=summary,
                             investigated_on=datetime.date.today().isoformat())
    finally:
        driver.close()
    config.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_file = config.REPORTS_DIR / f"{state['claim_id']}.json"
    brief = dict(state["report_brief"], summary_line=summary, text=state["report_text"],
                 investigated_on=datetime.date.today().isoformat())
    # default=str writes dates as text; sort_keys keeps the file the same for the same brief.
    report_file.write_text(json.dumps(brief, indent=2, default=str, sort_keys=True), encoding="utf-8")
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
        if state.get("loop_count", 0) == 0 and count_lawsuits([state["claim_id"]]) > 0:
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
    if finished_agent == "save_result":
        return "human_approval" if state.get("approval_wanted") else END
    if finished_agent == "human_approval":
        return "start_next_round" if state.get("human_decision") == "more" else END
    return END


def build_workflow(checkpointer=None):
    """Build and compile the LangGraph graph. Agents are looked up here, when the graph is built."""
    nodes = {
        "intake": intake, "graph_investigator": graph_investigator, "evidence": evidence,
        "litigation_analyst": litigation_analyst, "risk_scoring": risk_scoring, "challenger": challenger,
        "start_next_round": start_next_round, "report_writer": report_writer, "save_result": save_result,
        "human_approval": human_approval,
    }
    graph = StateGraph(InvestigationState)
    for name, function in nodes.items():
        graph.add_node(name, function)
        # partial(choose_next_agent, name) = a function that calls choose_next_agent(name, state).
        graph.add_conditional_edges(name, partial(choose_next_agent, name))
    graph.add_edge(START, "intake")
    return graph.compile(checkpointer=checkpointer)


def investigate_claim(claim_id, get_human_answer=None):
    """Run the whole investigation on one claim. Return the final state.

    get_human_answer(pause_value) returns {"decision", "reason"}. When it is None, there is no
    approval step (tests, and V15 with approval turned off)."""
    workflow = build_workflow(InMemorySaver())
    run_config = {"configurable": {"thread_id": f"investigate-{claim_id}-{uuid.uuid4()}"},
                  "recursion_limit": RECURSION_LIMIT}
    state = workflow.invoke({"claim_id": claim_id, "loop_count": 0, "approval_wanted": get_human_answer is not None},
                            run_config)
    # A paused run returns its state with an "__interrupt__" entry. Resume it with the answer.
    while "__interrupt__" in state:
        answer = get_human_answer(state["__interrupt__"][0].value)
        state = workflow.invoke(Command(resume=answer), run_config)
    return state
