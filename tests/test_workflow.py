"""Tests of src/workflow.py and the chat command of main.py (new system).

The whole chat runs: planner -> search agents -> MCP servers -> real graph (Neo4j must be running)
-> answer writer. Only the LLM is a fake: each agent gets its own scripted answers.
"""

import pytest
from langchain_core.messages import AIMessage

import main
from src.agents import answer_writer, planner
from src.mcp_servers import call_server_tool
from src.workflow import after_planner, build_chat_workflow, chat_turn


def call(name, arguments, call_id):
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": arguments, "id": call_id}]
    )


@pytest.fixture
def model(monkeypatch):
    """Scripted answers for the planner, the search agents and the writer. Records what each one received."""

    class FakeModel:
        def __init__(self):
            self.script, self.received = [], []

        def __call__(
            self, messages, tools, system_prompt, one_tool_at_a_time=False, **settings
        ):
            self.received.append(list(messages))
            assert self.script, "called more often than the test expected"
            return self.script.pop(0)

    fakes = {"planner": FakeModel(), "agents": FakeModel(), "writer": FakeModel()}
    monkeypatch.setattr(planner, "ask_llm_with_tools", fakes["planner"])
    monkeypatch.setattr(call_server_tool, "ask_llm_with_tools", fakes["agents"])
    monkeypatch.setattr(answer_writer, "ask_llm_with_tools", fakes["writer"])
    return fakes


def test_after_the_planner_comes_the_agent_it_asked_or_the_writer():
    assert (
        after_planner({"messages": [call("ask_scorer", {"task": "x"}, "r1")]})
        == "scorer"
    )
    assert (
        after_planner({"messages": [call("ask_document_search", {"task": "x"}, "r1")]})
        == "document_search"
    )
    assert (
        after_planner({"messages": [call("ask_graph_query", {"task": "x"}, "r1")]})
        == "graph_query"
    )
    assert (
        after_planner({"messages": [call("ask_global_search", {"task": "x"}, "r1")]})
        == "global_search"
    )
    assert after_planner({"messages": [AIMessage("Note: done.")]}) == "answer_writer"


def test_a_question_and_a_follow_up_in_one_session(model, capsys):
    graph = build_chat_workflow()
    # Message 1: the planner asks local search, then lets the writer reply.
    model["planner"].script = [
        call(
            "ask_global_search",
            {"task": "Groups of claims that share an address"},
            "r1",
        ),
        AIMessage("Note: list the groups."),
        call("ask_scorer", {"task": "Score of C-1026"}, "r2"),
        AIMessage("Note: explain the score of C-1026."),
    ]
    model["agents"].script = [
        call("find_shared_groups", {"kind": "address"}, "t1"),
        AIMessage("9 groups."),
        call("get_claim_score", {"claim_id": "C-1026"}, "t2"),
        AIMessage("C-1026 is Medium."),
    ]
    model["writer"].script = [
        AIMessage("9 groups share an address. The biggest has 6 claims, first C-1026."),
        AIMessage("C-1026 is Medium. It needs human review."),
    ]
    chat_turn(graph, "session-1", "Are there any claims which share the same address?")
    chat_turn(graph, "session-1", "Why is the first one worth a look?")
    output = capsys.readouterr().out
    # The log shows: where the planner sends the task, the agent's tools, each tool call, and the check.
    assert (
        "[planner] asks global_search: Groups of claims that share an address" in output
    )
    assert (
        "[global_search] tools it may use: list_communities, get_community, find_shared_groups"
        in output
    )
    assert "[global_search] calls find_shared_groups(kind=address) -> ok" in output
    assert "[scorer] calls get_claim_score(claim_id=C-1026) -> ok" in output
    assert "[planner] every part is covered. Note: Note: list the groups." in output
    assert "[answer writer] the reply passed the check. Sources added: 1" in output
    assert "- Graph groups of claims that share the same address" in output
    # Memory: for message 2 the planner got message 1, the agent's findings and the writer's reply.
    history = model["planner"].received[2]
    assert [message.type for message in history] == [
        "human",
        "ai",
        "tool",
        "ai",
        "ai",
        "human",
    ]
    assert (
        history[4].name == "answer_writer" and '"group_count": 9' in history[2].content
    )


def test_one_question_can_use_the_three_new_agents(model, capsys):
    # Build steps 3 to 5: global search, graph query and the hybrid document search in one message.
    model["planner"].script = [
        call(
            "ask_global_search",
            {"task": "Find the biggest groups of linked claims"},
            "r1",
        ),
        call("ask_graph_query", {"task": "Count the claims of each status"}, "r2"),
        call(
            "ask_document_search",
            {"task": "Which claims mention home stretching?"},
            "r3",
        ),
        AIMessage(
            "Note: name the biggest group, the counts and the claims about stretching."
        ),
    ]
    model["agents"].script = [
        call("list_communities", {}, "t1"),
        AIMessage("COM-01 is the biggest group."),
        call(
            "run_read_query",
            {
                "query": "MATCH (c:Claim) RETURN c.status AS status, count(*) AS claims LIMIT 10"
            },
            "t2",
        ),
        AIMessage("500 claims in three statuses."),
        call("search_all_documents", {"topic": "home stretching instructions"}, "t3"),
        AIMessage("Several claims mention home stretching."),
    ]
    model["writer"].script = [
        AIMessage("The biggest group is COM-01. The 500 claims are in three statuses.")
    ]
    chat_turn(build_chat_workflow(), "session-3", "Rings, statuses and stretching?")
    output = capsys.readouterr().out
    assert "[global_search] calls list_communities() -> ok" in output
    assert "[graph_query] calls run_read_query(query=MATCH (c:Claim)" in output
    assert (
        "[document_search] calls search_all_documents(topic=home stretching" in output
    )
    assert "- Communities of linked claims (graph)" in output
    assert "- Read-only graph query: MATCH (c:Claim) RETURN c.status" in output
    # The writer got the findings of all three agents.
    assert '"agent": "global_search"' in model["writer"].received[0][0].content


def test_a_greeting_needs_no_agent(model, capsys):
    model["planner"].script = [
        AIMessage("Note: greet the person and say what you can do.")
    ]
    model["writer"].script = [
        AIMessage("Hello. Ask me about claims, links, documents or scores.")
    ]
    chat_turn(build_chat_workflow(), "session-2", "Hi")
    assert "Hello." in capsys.readouterr().out and model["agents"].received == []


def test_a_new_session_has_no_memory(model):
    graph = build_chat_workflow()
    model["planner"].script = [AIMessage("Note: greet."), AIMessage("Note: greet.")]
    model["writer"].script = [AIMessage("Hello."), AIMessage("Hello again.")]
    chat_turn(graph, "session-a", "Hi")
    chat_turn(graph, "session-b", "Hi")
    assert len(model["planner"].received[1]) == 1


def test_main_has_only_the_chat_for_questions():
    commands = main.build_argument_parser()._subparsers._group_actions[0].choices
    assert (
        "chat" in commands and "investigate" not in commands and "ask" not in commands
    )


def test_the_chat_command_keeps_one_session(model, monkeypatch, capsys):
    typed = iter(["Hi", "And again?", "exit"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(typed))
    model["planner"].script = [
        AIMessage("Note: greet."),
        AIMessage("Note: greet again."),
    ]
    model["writer"].script = [AIMessage("Hello."), AIMessage("Still here.")]
    main.run_chat()
    assert (
        len(model["planner"].received[1]) == 4
    )  # human, note, reply, human: message 2 saw message 1


def test_debug_chat_shows_each_step_of_one_message(model, capsys):
    import debug_chat

    model["planner"].script = [
        call("ask_scorer", {"task": "Score of C-1088"}, "r1"),
        AIMessage("Note: explain the score."),
    ]
    model["agents"].script = [
        call("get_claim_score", {"claim_id": "C-1088"}, "t1"),
        AIMessage("C-1088 is High."),
    ]
    model["writer"].script = [AIMessage("C-1088 is High. It needs human review.")]
    session = {"configurable": {"thread_id": "debug-1"}}
    debug_chat.ask_question(build_chat_workflow(), session, "Why is C-1088 High?")
    output = capsys.readouterr().out
    assert "--- Step 1: planner finished. It added:\n  asks: ask_scorer" in output
    assert (
        "--- Step 2: scorer finished. It added:\n  findings: C-1088 is High." in output
    )
    assert "[scorer] calls get_claim_score(claim_id=C-1088) -> ok" in output
    assert "PATH: planner -> scorer -> planner -> answer_writer" in output
    assert "text: C-1088 is High. It needs human review." in output
