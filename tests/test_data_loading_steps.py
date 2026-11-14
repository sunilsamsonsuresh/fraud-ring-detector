"""Tests of the files in src/data_loading/ that need no database.

The expected answers are worked out by hand (in the comments). One test reads the saved LLM answers in
data/cache/, so building the graph again costs nothing.
"""

import datetime
import re

import pytest

from src import config
from src.data_loading import (
    extract_entities_from_pages,
    extract_findings_from_pages,
    find_document_loss_date,
    finding_features,
    load_tables_into_graph,
    match_entities_to_graph_nodes,
    parse_pdf_values,
    pdf_loading_queries,
    read_pdf_pages,
    split_pages_into_chunks,
    table_loading_queries,
)

# --- Chunks ---


def test_a_page_is_cut_into_overlapping_chunks():
    # 7 words, 4 in a chunk, 1 in the overlap: chunk 1 = words 1-4, chunk 2 starts at word 4 = words 4-7.
    chunks = split_pages_into_chunks.split_page_into_chunks(
        "a b c d e f g", 2, max_words=4, overlap_words=1
    )
    assert [chunk["text"] for chunk in chunks] == ["a b c d", "d e f g"]
    assert [(chunk["page_number"], chunk["chunk_number"]) for chunk in chunks] == [
        (2, 1),
        (2, 2),
    ]


def test_chunks_of_an_empty_page_and_a_bad_overlap():
    assert split_pages_into_chunks.split_page_into_chunks("", 1) == []
    with pytest.raises(ValueError):
        split_pages_into_chunks.split_page_into_chunks(
            "a b c", 1, max_words=3, overlap_words=3
        )


# --- Reading a PDF ---


def test_the_footer_is_removed_and_a_missing_file_gives_a_clear_error():
    text = f"line one\n{config.PDF_FOOTER_TEXT}  |  Page 1\nline two"
    assert read_pdf_pages.remove_footer(text) == "line one\nline two"
    with pytest.raises(RuntimeError, match="PDF not found"):
        read_pdf_pages.read_pdf_pages(config.PDFS_DIR / "C-1088" / "nothing.pdf")


# --- Values written in PDFs ---


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2024-03-05", datetime.date(2024, 3, 5)),
        ("3/5/2024", datetime.date(2024, 3, 5)),
        ("March 5, 2024", datetime.date(2024, 3, 5)),
        ("5 Mar 2024", datetime.date(2024, 3, 5)),
        ("3-5-24", datetime.date(2024, 3, 5)),
        ("not a date", None),
    ],
)
def test_the_five_date_styles(text, expected):
    assert parse_pdf_values.parse_date(text) == expected


def test_phone_text_and_codes():
    assert parse_pdf_values.normalize_phone("(713) 555 0142") == "713-555-0142"
    assert parse_pdf_values.normalize_phone("1-713-555-0142") == "713-555-0142"
    assert parse_pdf_values.normalize_phone("555-0142") == ""
    assert parse_pdf_values.normalize_code("pje 3330") == "PJE3330"
    assert parse_pdf_values.normalize_text("Reyes,  DC.") == "reyes dc"


def test_a_value_is_on_the_page_without_case_and_line_breaks():
    assert parse_pdf_values.appears_on_page(
        "rear-ended at a light", "He was Rear-Ended\nat a light."
    )
    assert not parse_pdf_values.appears_on_page("rear-ended at a light", "He was hit.")


def test_json_inside_an_answer_text():
    assert parse_pdf_values.parse_json_object('Here: ```json {"a": 1} ```') == {"a": 1}
    assert parse_pdf_values.parse_json_object("no json") is None
    assert parse_pdf_values.parse_json_object("[1, 2]") is None


# --- The loss date of a document ---


def test_the_loss_date_of_a_document():
    table_date = datetime.date(2024, 5, 1)
    page_1 = {"field": "loss_date", "value_as_written": "May 1, 2024", "page_number": 1}
    page_2 = {"field": "loss_date", "value_as_written": "2024-05-04", "page_number": 2}
    assert find_document_loss_date.document_loss_date(table_date, [page_1]) == (
        table_date,
        1,
        False,
    )
    assert find_document_loss_date.document_loss_date(table_date, [page_1, page_2]) == (
        datetime.date(2024, 5, 4),
        2,
        True,
    )
    assert find_document_loss_date.document_loss_date(table_date, []) == (
        None,
        None,
        False,
    )


# --- Entities of a page: plain code checks the LLM answer ---


def test_an_invented_entity_and_a_wrong_loss_date_are_dropped():
    page_text = "Date of loss: 2024-05-01\nClaimant: Ana Reyes, phone 713-555-0142\nTreated at Bayou Clinic.\nVisit on 2024-06-09."
    answer = {
        "people": [{"name": "Ana Reyes", "role": "claimant", "phone": "713-555-0142"}],
        "organizations": [
            {"name": "Bayou Clinic", "type": "clinic"},
            {"name": "Invented Law Firm", "type": "law_firm"},
        ],
        "loss_dates": [
            {"date": "2024-05-01", "words_before": "Date of loss:"},
            {"date": "2024-06-09", "words_before": "Visit on"},
        ],
    }  # a visit date, not a loss date
    entities, facts, rejected = extract_entities_from_pages.entities_and_facts(
        answer, page_text, "Ana Reyes"
    )
    assert [(e["entity_type"], e["value"]) for e in entities] == [
        ("claimant", "Ana Reyes"),
        ("phone", "713-555-0142"),
        ("clinic", "Bayou Clinic"),
    ]
    assert [(f["field"], f["value_as_written"]) for f in facts] == [
        ("phone", "713-555-0142"),
        ("loss_date", "2024-05-01"),
    ]
    assert len(rejected) == 2 and any("Invented Law Firm" in text for text in rejected)


# --- Matching entities to graph nodes ---


def test_matching_needs_exactly_one_node():
    clinic = {"element_id": "e1", "label": "Provider", "node_id": "PRV-001"}
    lookups = {
        "provider": {"bayou clinic": [clinic], "twin": [clinic, clinic]},
        "claimant": {},
    }
    match = match_entities_to_graph_nodes.match_entity
    assert match({"entity_type": "clinic", "value": "Bayou Clinic"}, lookups) == (
        clinic,
        "exact",
        "",
    )
    assert (
        match({"entity_type": "clinic", "value": "Twin"}, lookups)[0] is None
    )  # two nodes: no guess
    assert match({"entity_type": "clinic", "value": "Nobody"}, lookups)[0] is None


def test_a_claimant_is_matched_by_name_and_birth_date_or_phone():
    first = {
        "element_id": "e1",
        "label": "Claimant",
        "node_id": "CL-1",
        "date_of_birth": datetime.date(1990, 1, 2),
        "phone_number": "713-555-0001",
    }
    second = dict(
        first,
        element_id="e2",
        node_id="CL-2",
        date_of_birth=datetime.date(1985, 5, 6),
        phone_number="713-555-0002",
    )
    lookups = {"claimant": {"ana reyes": [first, second]}}
    match = match_entities_to_graph_nodes.match_entity
    entity = {
        "entity_type": "claimant",
        "value": "Ana Reyes",
        "date_of_birth_text": "",
        "phone_text": "",
    }
    assert match(entity, lookups)[0] is None  # same name twice, nothing else
    assert match(dict(entity, date_of_birth_text="May 6, 1985"), lookups)[1:] == (
        "name + date of birth",
        "",
    )
    assert (
        match(dict(entity, phone_text="(713) 555-0001"), lookups)[0]["node_id"]
        == "CL-1"
    )
    assert match(entity, {"claimant": {"ana reyes": [first]}})[1] == "name only"


# --- Findings: plain code checks the LLM answer ---


def test_findings_are_checked():
    page = {
        "page_number": 1,
        "text": "March 5, 2024\nThe vehicle has a small scratch on the rear bumper.\n",
    }
    answer = {
        "findings": [
            {
                "feature": "damage_crash_fit",
                "rating": "Strong",
                "confidence": "High",
                "quote": "small scratch on the rear bumper",
                "reason": "fits",
            },
            {
                "feature": "damage_crash_fit",
                "rating": "Strong",
                "confidence": "High",
                "quote": "small scratch on the rear bumper",
                "reason": "twice",
            },
            {
                "feature": "duplicate_billing",
                "rating": "Confirmed",
                "confidence": "High",
                "quote": "the same part was billed two times",
                "reason": "invented quote",
            },
            {
                "feature": "labor_hours_plausibility",
                "rating": "Big",
                "confidence": "High",
                "quote": "small scratch on the rear bumper",
                "reason": "bad rating",
            },
            {
                "feature": "prior_damage_evidence",
                "rating": "None",
                "confidence": "Sure",
                "quote": "small scratch on the rear bumper",
                "reason": "bad confidence",
            },
            {
                "feature": "duplicate_billing",
                "rating": "None",
                "confidence": "High",
                "quote": "short",
                "reason": "x",
            },
            {
                "feature": "treatment_growth",
                "rating": "Normal",
                "confidence": "High",
                "quote": "small scratch on the rear bumper",
                "reason": "not read from this document type",
            },
        ]
    }
    kept, dropped = extract_findings_from_pages.check_findings(
        answer, page, "repair_estimate", "D-1", datetime.date(2024, 1, 1)
    )
    assert len(kept) == 1
    finding = kept[0]
    assert (finding["finding_id"], finding["value"], finding["severity_rank"]) == (
        "D-1-p1-damage_crash_fit",
        "Strong",
        0,
    )
    assert finding["note_date"] == datetime.date(2024, 3, 5)
    assert [item["reason"] for item in dropped] == [
        "the feature was rated twice on this page",
        "the quote is not on the page",
        "rating 'Big' is not allowed",
        "confidence 'Sure' is not allowed",
        "the quote is missing or too short",
        "feature 'treatment_growth' is not read from a repair_estimate",
    ]


def test_a_number_finding_and_a_birth_date_before_the_loss():
    feature = finding_features.FEATURES_BY_CODE["occupants_listed"]
    assert [
        extract_findings_from_pages.checked_value(feature, value)
        for value in [3, "2", -1, "x", True]
    ] == [3, 2, None, None, None]
    text = "June 1, 1980\nClaimant born above.\nMarch 5, 2024\nThe note is here.\n"
    # The loss date is 2024-01-01, so the birth date (1980) does not count. Only March 5 counts.
    assert extract_findings_from_pages.note_date_of(
        text, "The note is here.", datetime.date(2024, 1, 1)
    ) == datetime.date(2024, 3, 5)


# --- Tables ---


def test_an_empty_id_makes_no_edge():
    rows = [
        {"claim_id": "C-1", "attorney_id": "A-1"},
        {"claim_id": "C-2", "attorney_id": ""},
    ]
    assert load_tables_into_graph.make_id_pairs(rows, "claim_id", "attorney_id") == [
        {"from_id": "C-1", "to_id": "A-1"}
    ]


def test_a_missing_table_gives_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="addresses.csv is missing"):
        load_tables_into_graph.read_tables(tmp_path)


def test_every_loading_query_takes_its_values_as_parameters():
    """Every load, link, save and delete query takes its values as a $parameter."""
    for module in (table_loading_queries, pdf_loading_queries):
        for name, text in vars(module).items():
            if name.isupper() and name.startswith(
                ("LOAD_", "LINK_", "SAVE_", "DELETE_")
            ):
                assert re.search(r"\$\w+", text), name


def test_the_saved_llm_answers_are_found_so_a_rebuild_costs_nothing(monkeypatch):
    # With no API key, any request that is not in data/cache/ stops with an error. So if this passes,
    # the prompts and the cache keys still match the saved answers, and building the graph again is free.
    from src.data_loading.read_pdf_pages import read_pdf_pages

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", "")
    file_path = config.PDFS_DIR / "C-1088" / "C-1088_fnol.pdf"
    pages = read_pdf_pages(file_path)
    for page in pages:
        assert extract_entities_from_pages.extract_page("fnol", page, len(pages))
        assert extract_findings_from_pages.ask_for_findings("fnol", page, len(pages))
