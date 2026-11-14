"""Tests of src/state.py (new system). No Neo4j, no LLM."""

from typing import get_type_hints

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from src.state import ChatState


def test_the_state_has_one_key_the_conversation():
    assert list(get_type_hints(ChatState)) == ["messages"]


def test_a_node_adds_messages_and_loses_none():
    def first(state):
        return {"messages": [AIMessage("one")]}

    def second(state):
        return {"messages": [AIMessage("two")]}

    builder = StateGraph(ChatState)
    builder.add_node("first", first)
    builder.add_node("second", second)
    builder.add_edge(START, "first")
    builder.add_edge("first", "second")
    builder.add_edge("second", END)
    final = builder.compile().invoke({"messages": [HumanMessage("hello")]})
    assert [message.text for message in final["messages"]] == ["hello", "one", "two"]
