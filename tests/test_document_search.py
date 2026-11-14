"""Tests of src/agents/document_search.py (new system).
Real MCP server and graph (Neo4j must be running; the first search loads the embedding model). Scripted fake LLM."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from src.agents import document_search
from src.mcp_servers import call_server_tool


def planner_asks(task):
    return {
        "messages": [
            HumanMessage("question"),
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "ask_document_search", "args": {"task": task}, "id": "r1"}
                ],
            ),
        ]
    }


@pytest.fixture
def model(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.script = []
            self.tools_seen = []

        def __call__(
            self, messages, tools, system_prompt, one_tool_at_a_time=False, **settings
        ):
            self.tools_seen = [tool["name"] for tool in tools]
            return self.script.pop(0)

    fake = FakeModel()
    fake.script = []
    monkeypatch.setattr(call_server_tool, "ask_llm_with_tools", fake)
    return fake


def test_it_sees_only_the_document_search(model):
    model.script = [AIMessage("Nothing.")]
    document_search.document_search(planner_asks("x"))
    assert model.tools_seen == [
        "search_all_documents",
        "search_claim_documents",
        "get_claim_findings",
    ]


def test_it_returns_passages_of_the_claim_with_pages(model):
    model.script = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_claim_documents",
                    "args": {"claim_id": "C-1088", "topic": "neck injury"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage("The records describe neck and back strain."),
    ]
    result = json.loads(
        document_search.document_search(
            planner_asks("What do the documents say about the injury?")
        )["messages"][0].content
    )
    passages = result["tool_answers"][0]["answer"]["facts"]["passages"]
    assert 1 <= len(passages) <= 5
    assert all(
        passage["source"].startswith("C-1088_") and ", page " in passage["source"]
        for passage in passages
    )


def test_with_no_claim_it_searches_all_documents(model):
    model.script = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "search_all_documents",
                    "args": {"topic": "home stretching instructions"},
                    "id": "t1",
                }
            ],
        ),
        AIMessage("Several claims mention home stretching."),
    ]
    result = document_search.document_search(
        planner_asks("Which claims mention home stretching?")
    )
    findings = json.loads(result["messages"][0].content)
    answer = findings["tool_answers"][0]["answer"]
    assert findings["tool_answers"][0]["tool"] == "search_all_documents"
    for passage in answer["facts"]["passages"]:
        assert passage["source"].startswith(passage["claim_id"] + "_")
