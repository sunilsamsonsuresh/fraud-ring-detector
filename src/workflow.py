"""The LangGraph workflow of the chat: which agent runs after which.

    question -> planner -> one search agent -> planner -> ... -> answer writer -> short reply

1. The planner splits the question into parts and asks ONE search agent for one part, or writes a short
   note when every part is covered.
2. The search agent (local search, document search, scorer, graph query or global search) does its task
   with its MCP tools.
   Its findings go back to the planner, which may ask another agent.
3. The answer writer writes a short reply. Plain code checks it and adds the sources.

The conversation lives in state["messages"]. The checkpointer keeps it for each thread ID:
one chat session = one thread ID = one memory. It lasts until the program stops.
"""

from langchain_core.messages import HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from src.agents.answer_writer import answer_writer
from src.agents.document_search import document_search
from src.agents.global_search import global_search
from src.agents.graph_query import graph_query
from src.agents.local_search import local_search
from src.agents.planner import AGENT_OF_TOOL, planner
from src.agents.scorer import scorer
from src.state import ChatState

SEARCH_AGENTS = {
    "local_search": local_search,
    "document_search": document_search,
    "scorer": scorer,
    "graph_query": graph_query,
    "global_search": global_search,
}


def after_planner(state):
    """Plain rule: if the planner asked an agent, run that agent. Else the answer writer replies."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return AGENT_OF_TOOL.get(last_message.tool_calls[0]["name"], "answer_writer")
    return "answer_writer"


def build_chat_workflow(checkpointer=None):
    """Make the compiled chat workflow. The default checkpointer keeps the memory in this program."""
    builder = StateGraph(ChatState)
    builder.add_node("planner", planner)
    for agent_name, agent_function in SEARCH_AGENTS.items():
        builder.add_node(agent_name, agent_function)
        builder.add_edge(
            agent_name, "planner"
        )  # findings always go back to the planner
    builder.add_node("answer_writer", answer_writer)
    builder.add_edge(START, "planner")
    builder.add_conditional_edges(
        "planner", after_planner, list(SEARCH_AGENTS) + ["answer_writer"]
    )
    builder.add_edge("answer_writer", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())


def chat_turn(graph, thread_id, question):
    """Run one message of a chat session and print the reply. The agents print their own steps as they work."""
    final_state = graph.invoke(
        {"messages": [HumanMessage(question)]},
        {"configurable": {"thread_id": thread_id}},
    )
    reply_text = final_state["messages"][-1].text
    print()
    print(reply_text)
    return reply_text
