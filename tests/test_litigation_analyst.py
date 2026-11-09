"""Step 8 tests: Litigation Analyst. (The v1 Risk Scoring tests were replaced by
tests/test_scoring.py in V7, because the v1 weighted sum was replaced by the rule engine.)

A fake LLM replaces the real one, so no API call is made.
"""

import json

import pytest

from src.agents import litigation_analyst

NEEDS_V1_DATA = "needs v1 data; replaced in V6 or V7"


def test_litigation_review_keeps_only_points_with_a_real_source():
    sources = {"C-1143_complaint.pdf, page 1"}
    answer = json.dumps({"assessment": "strengthens_concern", "reason": "Unusual timing.",
                         "points": [{"finding": "Filed 7 days before the deadline.",
                                     "source": "C-1143_complaint.pdf, page 1"},
                                    {"finding": "Invented.", "source": "C-9999_complaint.pdf, page 4"}]})
    review, warnings = litigation_analyst.parse_review("```json\n" + answer + "\n```", sources)
    assert review["assessment"] == "strengthens_concern" and len(review["points"]) == 1
    assert len(warnings) == 1
    assert litigation_analyst.parse_review('{"assessment": "fraud"}', sources)[0] is None
    assert litigation_analyst.parse_review("not json", sources)[0] is None
    guilty = json.dumps({"assessment": "neutral", "reason": "The plaintiff is guilty.", "points": []})
    assert litigation_analyst.parse_review(guilty, sources)[0] is None


@pytest.mark.skip(reason=NEEDS_V1_DATA)
def test_claim_without_a_lawsuit_gets_facts_but_no_llm_call(monkeypatch):
    def llm_must_not_be_called(*arguments, **keywords):
        raise AssertionError("The LLM was called for a claim without a lawsuit.")
    monkeypatch.setattr(litigation_analyst, "ask_llm", llm_must_not_be_called)
    result = litigation_analyst.litigation_analyst({"claim_id": "C-1037", "linked_claims": []})
    assert result["litigation_facts"]["own_lawsuit"] is None
    assert result["litigation_review"] is None
