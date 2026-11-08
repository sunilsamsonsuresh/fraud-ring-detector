"""Step 6 tests: PDF reading, chunks, value parsing, matching, conflicts and the Intake agent.

The agent tests need Neo4j and the real data in data/. A fake LLM replaces the real one.
The fake answers use only values that really are on the page, so the MENTIONS edges
they save are the same ones a real run saves.
"""

import datetime
import json

import pytest

from src import config
from src.agents import intake
from src.documents import extraction
from src.documents.chunker import split_page_into_chunks
from src.documents.conflicts import find_conflicts
from src.documents.entity_matching import load_match_lookups, match_entity
from src.documents.pdf_reader import read_pdf_pages
from src.documents.value_parsing import normalize_phone, parse_amount, parse_date
from src.graph.connection import open_neo4j_driver
from src.graph.loader import load_graph

# Planted conflict: the claims table says 2024-05-01, this police report says 28 Apr 2024.
POLICE_REPORT_ANSWER = json.dumps({
    "people": [{"name": "Jason Kaufman", "role": "claimant", "phone": "713-555-1556"},
               {"name": "Ronald Davis", "role": "officer"},
               {"name": "Ghost Person", "role": "claimant"}],          # not on the page: must be dropped
    "organizations": [{"name": "Gulf Coast Metro Traffic Division", "type": "police"}],
    "vehicles": [{"vin": "", "license_plate": "RKM2884"}],
    "loss_dates": [{"date": "28 Apr 2024", "words_before": "Crash date:"}],
})


def fake_ask_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
    if "Crash Report" in user_prompt:
        return "```json\n" + POLICE_REPORT_ANSWER + "\n```"
    return "{}"


@pytest.fixture(scope="module")
def driver():
    load_graph(config.TABLES_DIR)
    neo4j_driver = open_neo4j_driver()
    yield neo4j_driver
    neo4j_driver.close()


# --- plain helpers ------------------------------------------------------------

def test_parse_date_reads_all_five_styles():
    expected = datetime.date(2024, 3, 5)
    for text in ["2024-03-05", "03/05/2024", "March 5, 2024", "5 Mar 2024", "3-5-24"]:
        assert parse_date(text) == expected, text
    assert parse_date("2-1-55") == datetime.date(1955, 2, 1)      # a two-digit year in the future means 19xx
    assert parse_date("next Tuesday") is None


def test_parse_amount_and_phone():
    assert parse_amount("$5,994.80") == 5994.80
    assert parse_amount("about five") is None
    assert normalize_phone("(713) 555 0142") == "713-555-0142"
    assert normalize_phone("+1 713.555.0142") == "713-555-0142"
    assert normalize_phone("555-0142") == ""


def test_chunks_overlap_and_keep_the_page_number():
    chunks = split_page_into_chunks("a b c d e f g", page_number=2, max_words=4, overlap_words=1)
    assert [chunk["text"] for chunk in chunks] == ["a b c d", "d e f g"]
    assert all(chunk["page_number"] == 2 for chunk in chunks)
    assert split_page_into_chunks("   ", page_number=1) == []
    with pytest.raises(ValueError):
        split_page_into_chunks("a b", page_number=1, max_words=3, overlap_words=3)


def test_pdf_reader_reads_pages_without_the_footer(tmp_path):
    pages = read_pdf_pages(config.PDFS_DIR / "C-1037" / "C-1037_medical_records.pdf")
    assert [page["page_number"] for page in pages] == [1, 2]
    assert "Mills Spine & Injury Center" in pages[0]["text"]
    assert "SYNTHETIC TEST DOCUMENT" not in pages[0]["text"]
    with pytest.raises(RuntimeError):
        read_pdf_pages(tmp_path / "missing.pdf")
    broken_file = tmp_path / "broken.pdf"
    broken_file.write_bytes(b"this is not a pdf")
    with pytest.raises(RuntimeError):
        read_pdf_pages(broken_file)


def test_llm_answer_is_cleaned_and_checked_against_the_page():
    page_text = "Patient: Michael Long\nDate of birth: 2-1-97\nClinic: Mills Spine & Injury Center"
    answer = {"people": [{"name": "Michael Long", "role": "claimant", "date_of_birth": "2-1-97"},
                         {"name": "Invented Name", "role": "claimant"}, "not a dict", {"name": "X", "role": 5}],
              "organizations": "not a list",
              "loss_dates": [None, {"date": "1 Jan 2020"}, {"date": "2-1-97", "words_before": "Date of birth:"}]}
    entities, facts, rejected = extraction.entities_and_facts(answer, page_text, "Michael Long")
    assert {"entity_type": "claimant", "value": "Michael Long", "date_of_birth_text": "2-1-97",
            "phone_text": ""} in entities
    assert "'Invented Name' (not on the page)" in rejected
    assert "'1 Jan 2020' (not on the page)" in rejected
    assert any(item.startswith("'2-1-97' as loss date") for item in rejected)   # no loss word before it
    assert facts == [{"field": "date_of_birth", "value_as_written": "2-1-97"}]
    assert extraction.parse_json_object("no json here") is None
    assert extraction.parse_json_object('["a list"]') is None


def test_find_conflicts_compares_only_values_on_both_sides():
    claim_facts = {"loss_date": datetime.date(2024, 5, 1), "repair_estimate_total": 5994.8,
                   "medical_bill_total": None, "phone": "713-555-1556"}
    page_facts = [
        {"field": "loss_date", "value_as_written": "28 Apr 2024"},       # differs -> conflict
        {"field": "loss_date", "value_as_written": "5-1-24"},            # same date, other style
        {"field": "repair_estimate_total", "value_as_written": "$5,994.80"},
        {"field": "medical_bill_total", "value_as_written": "$100.00"},  # table has no value
        {"field": "phone", "value_as_written": "(713) 555-1556"},
        {"field": "loss_date", "value_as_written": "soon"},              # unreadable -> warning
    ]
    for fact in page_facts:
        fact.update({"document_id": "D", "page_number": 1})
    conflicts, warnings = find_conflicts(claim_facts, page_facts)
    assert [(c["field"], c["document_value"]) for c in conflicts] == [("loss_date", "28 Apr 2024")]
    assert len(warnings) == 1


# --- matching and the agent (need Neo4j) ---------------------------------------

def test_matching_rules(driver):
    lookups = load_match_lookups(driver)
    target, method, _ = match_entity({"entity_type": "phone", "value": "(713) 555-1556"}, lookups)
    assert target["label"] == "Phone" and method == "exact"
    target, method, _ = match_entity({"entity_type": "claimant", "value": "Michael Long",
                                      "date_of_birth_text": "2-1-97"}, lookups)
    assert target["label"] == "Claimant" and method == "name + date of birth"
    target, _, reason = match_entity({"entity_type": "claimant", "value": "Nobody Atall"}, lookups)
    assert target is None and reason == "no claimant has this name"
    target, method, _ = match_entity({"entity_type": "clinic", "value": "mills spine & injury center"}, lookups)
    assert target["label"] == "Provider"


def test_intake_finds_the_planted_conflict_and_saves_mentions(driver, monkeypatch):
    monkeypatch.setattr(extraction, "ask_llm", fake_ask_llm)
    result = intake.intake({"claim_id": "C-1007"})

    assert {"document_id": "C-1007-police_report", "page_number": 1, "field": "loss_date",
            "table_value": "2024-05-01", "document_value": "28 Apr 2024"} in result["document_conflicts"]
    statuses = {(e["entity_type"], e["value_as_written"]): e["status"] for e in result["entity_results"]}
    assert statuses[("claimant", "Jason Kaufman")] == "matched"
    assert statuses[("license_plate", "RKM2884")] == "matched"
    assert statuses[("other_person", "Ronald Davis")] == "not_in_graph"
    assert ("claimant", "Ghost Person") not in statuses
    assert any("Ghost Person" in warning for warning in result["intake_warnings"])

    records, _, _ = driver.execute_query(
        "MATCH (:Claim {claim_id: 'C-1007'})-[:HAS_DOCUMENT]->(:Document {document_id: 'C-1007-police_report'})"
        "-[edge:MENTIONS]->(:Claimant) RETURN edge.page_number AS page_number")
    assert [record["page_number"] for record in records] == [1]


def test_bad_json_does_not_crash_the_run(driver, monkeypatch):
    prompts = []

    def always_bad(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
        prompts.append(user_prompt)
        return "Sorry, I cannot do that"
    monkeypatch.setattr(extraction, "ask_llm", always_bad)
    result = intake.intake({"claim_id": "C-1007"})
    page_count = sum(len(read_pdf_pages(config.PDFS_DIR / "C-1007" / row["file_name"]))
                     for row in intake.read_claim_documents("C-1007"))
    assert len(prompts) == 2 * page_count                      # one retry per page, then skip
    assert result["entity_results"] == []
    assert sum("valid JSON" in warning for warning in result["intake_warnings"]) == page_count


def test_unknown_claim_gives_an_error():
    assert intake.intake({"claim_id": "C-9999"}) == {"error_message": "No documents were found for claim C-9999."}
