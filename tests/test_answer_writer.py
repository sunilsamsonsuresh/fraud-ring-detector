"""Tests of src/agents/answer_writer.py (new system). The LLM is a fake. No Neo4j."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents import answer_writer
from src.agents.answer_writer import collect_sources, find_problems_in_reply

SCORE_ANSWER = {
    "facts": {
        "claim_id": "C-1088",
        "total_score": 22.2,
        "band": "High",
        "fired_rules": [
            {
                "rule_id": "BI-5",
                "proof": {
                    "findings": [
                        {"document_id": "C-1088-adjuster_file", "page_number": 1}
                    ]
                },
            }
        ],
    },
    "sources": ["Scoring rules applied to C-1088"],
}
FINDINGS = {
    "agent": "scorer",
    "task": "Score C-1088",
    "findings": "C-1088 is High.",
    "tool_answers": [
        {
            "tool": "get_claim_score",
            "arguments": {"claim_id": "C-1088"},
            "answer": SCORE_ANSWER,
        }
    ],
}


def conversation(*extra):
    return [
        HumanMessage("Hi"),
        AIMessage("Hello.", name="answer_writer"),
        HumanMessage("Why is C-1088 High?"),
        AIMessage(
            content="",
            tool_calls=[
                {"name": "ask_scorer", "args": {"task": "Score C-1088"}, "id": "r1"}
            ],
        ),
        ToolMessage(json.dumps(FINDINGS), tool_call_id="r1"),
        AIMessage("Note: explain the score."),
        *extra,
    ]


@pytest.fixture
def model(monkeypatch):
    class FakeModel:
        answer = "C-1088 is High (22.2) because rule BI-5 fired. It needs human review."

        def __init__(self):
            self.calls = []

        def __call__(
            self, messages, tools, system_prompt, one_tool_at_a_time=False, **settings
        ):
            self.calls.append({"prompt": messages[0].text, "tools": tools})
            if isinstance(self.answer, Exception):
                raise self.answer
            return AIMessage(self.answer)

    fake = FakeModel()
    fake.calls = []
    monkeypatch.setattr(answer_writer, "ask_llm_with_tools", fake)
    return fake


def test_the_reply_is_checked_and_gets_the_sources(model):
    reply = answer_writer.answer_writer({"messages": conversation()})["messages"][0]
    assert reply.name == "answer_writer"
    assert reply.text.startswith(model.answer)
    assert (
        "- Scoring rules applied to C-1088" in reply.text
        and "- C-1088-adjuster_file, page 1" in reply.text
    )


def test_the_writer_gets_the_history_the_question_the_note_and_the_findings_and_no_tools(
    model,
):
    answer_writer.answer_writer({"messages": conversation()})
    prompt = model.calls[0]["prompt"]
    assert "Person: Hi" in prompt and "Reply: Hello." in prompt
    assert (
        "New question:\nWhy is C-1088 High?" in prompt
        and "Note: explain the score." in prompt
    )
    assert '"findings": "C-1088 is High."' in prompt
    assert model.calls[0]["tools"] == []


def test_an_unknown_claim_or_rule_or_guilty_is_not_shown(model):
    model.answer = "C-1999 is guilty, and CT-7 fired."
    text = answer_writer.answer_writer({"messages": conversation()})["messages"][0].text
    assert (
        text.startswith("I cannot show this answer")
        and "C-1999" in text
        and "CT-7" in text
        and "guilty" in text
    )


def test_a_claim_id_the_person_wrote_is_allowed(model):
    model.answer = "I have no data for C-1234 yet. Do you want me to look it up?"
    messages = [
        HumanMessage("Tell me about C-1234"),
        AIMessage("Note: ask if they want a lookup."),
    ]
    assert (
        answer_writer.answer_writer({"messages": messages})["messages"][0].text
        == model.answer
    )


def test_an_llm_failure_becomes_a_reply_not_a_crash(model):
    model.answer = RuntimeError("Cannot reach the Anthropic API.")
    text = answer_writer.answer_writer({"messages": conversation()})["messages"][0].text
    assert "Cannot reach the Anthropic API." in text


def test_sources_have_no_duplicates_and_include_passages():
    passages = {
        "facts": {
            "passages": [
                {"source": "C-1088_fnol.pdf, page 1"},
                {"source": "C-1088_fnol.pdf, page 1"},
            ]
        },
        "sources": [],
    }
    results = [{"tool_answers": [{"answer": passages}, {"answer": SCORE_ANSWER}]}]
    assert collect_sources(results) == [
        "C-1088-fnol, page 1",  # the passage's file name is written as the document ID
        "Scoring rules applied to C-1088",
        "C-1088-adjuster_file, page 1",
    ]


def test_the_checker_lists_every_problem():
    assert find_problems_in_reply("C-1088 and BI-5.", '"C-1088" "BI-5"') == []
    assert (
        len(find_problems_in_reply("C-1999 is guilty and NL-3 fired.", '"C-1088"')) == 3
    )


def test_the_writer_is_told_to_be_short_and_answer_every_part():
    prompt = answer_writer.SYSTEM_PROMPT
    assert "one to three sentences" in prompt and "at most five bullet points" in prompt
    assert "Answer every part of the question" in prompt and "150 words" in prompt


def test_one_page_is_one_source_whatever_its_format():
    from src.agents.answer_writer import same_page_text

    assert (
        same_page_text("C-1088_medical_records.pdf, page 2")
        == "C-1088-medical_records, page 2"
    )
    assert same_page_text("Graph links of C-1088") == "Graph links of C-1088"
    passage = {
        "facts": {"passages": [{"source": "C-1088_adjuster_file.pdf, page 1"}]},
        "sources": [],
    }
    finding = {"facts": {"findings": []}, "sources": ["C-1088-adjuster_file, page 1"]}
    results = [{"tool_answers": [{"answer": passage}, {"answer": finding}]}]
    assert collect_sources(results) == ["C-1088-adjuster_file, page 1"]
