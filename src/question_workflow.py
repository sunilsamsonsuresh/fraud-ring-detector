"""Questions in plain English: the LangGraph graph for `ask` and `chat` (PLAN-v2.md A9, V14).

question_router (LLM: picks one intent)
  -> check_question (plain code: checks every value; may stop with a message)
  -> run_question_tool (plain code: the fixed path of the intent)   [skipped when there is a message]
  -> answer_writer (LLM: words from the tool result; plain code adds the sources)
The `investigate` command does not use this graph. It starts the investigation workflow directly.

Chat memory: the checkpointer keeps the state of each thread (one chat = one thread ID).
The next question in the same thread starts with the saved state, so current_case is still
there and "Why?" is about the last claim. InMemorySaver forgets everything when the program
ends, so memory lasts for the session only (CLAUDE.md, rule 15).
"""

import uuid
from functools import partial

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.answer_writer import answer_writer
from src.agents.question_router import question_router
from src.graph.connection import open_neo4j_driver
from src.questions.checks import check_route
from src.questions.tools import run_tool
from src.state import QuestionState

EXIT_WORDS = ["exit", "quit", "bye"]


def check_question(state):
    driver = open_neo4j_driver()
    try:
        parameters, message = check_route(driver, state["route"], state["question"], state.get("current_case"))
    finally:
        driver.close()
    # Every turn sets tool_result again, so an old result from the last question is never reused.
    return {"parameters": parameters, "tool_result": {"message": message} if message else None}


def run_question_tool(state):
    driver = open_neo4j_driver()
    try:
        tool_result = run_tool(driver, state["route"]["intent"], state["parameters"])
    finally:
        driver.close()
    update = {"tool_result": tool_result}
    if "claim_id" in state["parameters"] and "message" not in tool_result:
        update["current_case"] = state["parameters"]["claim_id"]      # the claim the chat talks about now
    return update


def choose_next_step(finished_step, state):
    """Plain if/else rules: no LLM decides the route."""
    if finished_step == "question_router":
        return "check_question"
    if finished_step == "check_question":
        return "answer_writer" if state["tool_result"] else "run_question_tool"
    if finished_step == "run_question_tool":
        return "answer_writer"
    return END


def build_question_workflow(checkpointer):
    steps = {"question_router": question_router, "check_question": check_question,
             "run_question_tool": run_question_tool, "answer_writer": answer_writer}
    graph = StateGraph(QuestionState)
    for name, function in steps.items():
        graph.add_node(name, function)
        graph.add_conditional_edges(name, partial(choose_next_step, name))
    graph.add_edge(START, "question_router")
    return graph.compile(checkpointer=checkpointer)


def new_chat():
    """Return (workflow, run config) for one chat session."""
    workflow = build_question_workflow(InMemorySaver())
    return workflow, {"configurable": {"thread_id": f"chat-{uuid.uuid4()}"}}


def answer_question(workflow, run_config, question):
    """One question in a chat (or alone). Return the state after the answer."""
    return workflow.invoke({"question": question}, run_config)


def ask_question(question):
    """The `ask` command: one question, a fresh session."""
    workflow, run_config = new_chat()
    return answer_question(workflow, run_config, question)


def chat_in_terminal(read_line=input, write=print):
    """The `chat` command. One session; it ends with exit, quit, bye or an empty line."""
    workflow, run_config = new_chat()
    write("Ask about claims, scores and rules. Type 'exit' to stop.")
    while True:
        question = read_line("> ").strip()
        if not question or question.lower() in EXIT_WORDS:
            return
        state = answer_question(workflow, run_config, question)
        write(state["answer"])
        if state.get("current_case"):
            write(f"(current claim: {state['current_case']})")
