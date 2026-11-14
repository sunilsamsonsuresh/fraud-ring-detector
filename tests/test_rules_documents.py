"""Tests of src/scoring/rules_documents.py (new system).

Most tests use made-up facts, so they need no Neo4j.
"""

import datetime

from src.scoring.rules_catalog import RULES_BY_ID
from src.scoring.rules_documents import DOCUMENT_RULE_CHECKS, check_as_7

LOSS = datetime.date(2025, 3, 1)


def document(number, loss_date_in_pdf, page_number=1):
    return {
        "document_id": f"C-0000-doc{number}",
        "document_type": "fnol",
        "loss_date_in_pdf": loss_date_in_pdf,
        "page_number": page_number,
    }


def facts_with(documents):
    return {"loss_date": LOSS, "document_loss_dates": documents}


def status(result):
    return result["status"]


def test_as_7_does_not_fire_when_every_document_gives_the_table_date():
    result = check_as_7(facts_with([document(1, LOSS), document(2, LOSS)]))
    assert status(result) == "not_fired"
    assert (
        result["proof"]["documents_checked"] == 2 and result["proof"]["conflicts"] == []
    )


def test_as_7_fires_for_one_different_date_even_one_day_off_and_names_document_and_page():
    one_day_off = LOSS + datetime.timedelta(days=1)
    result = check_as_7(
        facts_with([document(1, LOSS), document(2, one_day_off, page_number=3)])
    )
    assert status(result) == "fired"
    assert result["proof"]["conflicts"] == ["C-0000-doc2 page 3: 2025-03-02"]
    assert result["proof"]["table_loss_date"] == LOSS


def test_as_7_lists_every_conflict():
    other = LOSS - datetime.timedelta(days=9)
    result = check_as_7(
        facts_with(
            [document(1, other), document(2, LOSS), document(3, other, page_number=2)]
        )
    )
    assert len(result["proof"]["conflicts"]) == 2


def test_as_7_skips_a_document_without_a_date_but_not_evaluated_when_none_has_one():
    skipped = check_as_7(facts_with([document(1, None, None), document(2, LOSS)]))
    assert status(skipped) == "not_fired" and skipped["proof"]["documents_checked"] == 1
    assert status(check_as_7(facts_with([document(1, None, None)]))) == "not_evaluated"
    assert status(check_as_7(facts_with([]))) == "not_evaluated"


def test_the_registry_has_as_7_and_it_is_in_the_catalog():
    assert sorted(DOCUMENT_RULE_CHECKS) == ["AS-7"]
    assert all(rule_id in RULES_BY_ID for rule_id in DOCUMENT_RULE_CHECKS)


# --- Same answers as the old system, on real claims ---
