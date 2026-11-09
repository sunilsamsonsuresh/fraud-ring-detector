"""V6 tests: findings (checks, note dates, merge, saving) and the loss date on each Document node.

A fake LLM replaces the real one, so no API call is made. The Neo4j tests use the real v2
PDFs and tables (generate-data --pdfs, load-graph). They write fake answers into real claims,
so the restore_claim fixture reads each claim again from the cache afterwards.
"""

import datetime
import json
import re

import pytest

from src import config
from src.agents import intake
from src.documents import extraction, feature_extraction
from src.documents.conflicts import document_loss_date
from src.documents.feature_extraction import check_findings, merge_findings, note_date_of
from src.graph import queries
from src.graph.connection import open_neo4j_driver
from src.llm import make_cache_key, read_cached_answer

LOSS_DATE = datetime.date(2024, 3, 1)
ADJUSTER_PAGE = {"page_number": 1, "text": (
    "Claim Notes\nClaimant: Jane Roe\nDate of birth:\n1980-02-02\n3-5-24\nCalled the claimant. She described a "
    "rear-end crash at a light.\n3-19-24\nIn a second call the claimant said the other car hit her side, and that "
    "two friends were in the car.\n")}


def finding(feature, rating, quote, confidence="High"):
    return {"feature": feature, "rating": rating, "confidence": confidence, "quote": quote, "reason": "r"}


def test_only_checked_findings_are_kept_and_every_drop_has_a_reason():
    answer = {"findings": [
        finding("account_stability", "Materially changed", "the claimant said the other car hit her side"),
        finding("occurrence_support", "Confirmed", "Three witnesses saw the crash."),          # invented quote
        finding("injury_crash_fit", "Very bad", "Called the claimant. She described"),           # not a rating
        finding("duplicate_billing", "None", "Called the claimant. She described"),              # not in notes
        finding("driver_status", "Listed", "Called the claimant.", confidence="Sure"),           # bad confidence
        finding("pre_existing_condition", "None", "Called"),                                     # quote too short
        finding("account_stability", "Stable", "Called the claimant. She described"),            # rated twice
        "not an object",
    ]}
    kept, dropped = check_findings(answer, ADJUSTER_PAGE, "adjuster_file", "C-1-adjuster_file", LOSS_DATE)
    assert [item["feature"] for item in kept] == ["account_stability"]
    assert kept[0]["severity_rank"] == 2 and kept[0]["finding_id"] == "C-1-adjuster_file-p1-account_stability"
    reasons = [item["reason"] for item in dropped]
    assert reasons == ["the quote is not on the page", "rating 'Very bad' is not allowed",
                       "feature 'duplicate_billing' is not read from a adjuster_file",
                       "confidence 'Sure' is not allowed", "the quote is missing or too short",
                       "the feature was rated twice on this page", "not a JSON object"]


def test_numbers_are_checked_for_the_occupant_count():
    page = {"page_number": 1, "text": "Occupants of each vehicle\nVehicle 1 (insured) Driver Ann Lee\n"}
    for rating, expected in [("2", 2), (3, 3), (True, None), ("two", None), (-1, None)]:
        kept, _ = check_findings({"findings": [finding("occupants_listed", rating, "Vehicle 1 (insured) Driver Ann Lee")]},
                                 page, "police_report", "D", LOSS_DATE)
        assert (kept[0]["value"] if kept else None) == expected, rating


def test_note_date_is_the_closest_date_line_above_the_quote():
    assert note_date_of(ADJUSTER_PAGE["text"], "the other car hit her side", LOSS_DATE) == datetime.date(2024, 3, 19)
    assert note_date_of(ADJUSTER_PAGE["text"], "She described a rear-end crash", LOSS_DATE) == datetime.date(2024, 3, 5)
    # Above the first note there is only a birth date, which is before the loss: no note date.
    assert note_date_of(ADJUSTER_PAGE["text"], "Claimant: Jane Roe", LOSS_DATE) is None


def test_merge_takes_the_worst_or_the_latest_value():
    def item(feature, value, rank, day, document_id="D"):
        return {"feature": feature, "value": value, "severity_rank": rank, "document_id": document_id,
                "page_number": 1, "note_date": datetime.date(2024, 3, day) if day else None}
    merged = merge_findings([item("treatment_growth", "Extreme", 3, 5), item("treatment_growth", "Normal", 0, 20),
                             item("occurrence_support", "Contradicted", 3, 5), item("occurrence_support", "Confirmed", 0, 20)])
    assert merged["treatment_growth"]["value"] == "Extreme"       # worst: a later "Normal" cannot undo it
    assert merged["occurrence_support"]["value"] == "Confirmed"    # latest: the newer note settles it


def test_document_loss_date_function():
    assert document_loss_date(LOSS_DATE, []) == (None, None, False)
    same = {"field": "loss_date", "value_as_written": "03/01/2024", "page_number": 1}
    other = {"field": "loss_date", "value_as_written": "28 Feb 2024", "page_number": 2}
    assert document_loss_date(LOSS_DATE, [same]) == (LOSS_DATE, 1, False)
    assert document_loss_date(LOSS_DATE, [same, other]) == (datetime.date(2024, 2, 28), 2, True)


# --- With Neo4j and the real v2 PDFs ---------------------------------------------------

@pytest.fixture(scope="module")
def truth():
    if not (config.PDFS_DIR / "documents.csv").exists():
        pytest.skip("No v2 PDFs. Run: python main.py generate-data --pdfs")
    with open(config.GROUND_TRUTH_FILE, encoding="utf-8") as file:
        return json.load(file)


def cache_only_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
    """The saved real answer, or LookupError. Never calls the API, so restoring a claim costs nothing."""
    cache_key = make_cache_key(model_name, system_prompt, user_prompt, max_tokens, effort)
    answer = read_cached_answer(config.CACHE_DIR / f"{cache_key}.json")
    if answer is None:
        raise LookupError("not in the cache")
    return answer


def read_claim_from_cache(claim_id):
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(extraction, "ask_llm", cache_only_llm)
        patch.setattr(feature_extraction, "ask_llm", cache_only_llm)
        intake.read_claim(claim_id, read_entities=True, read_findings=True)


@pytest.fixture
def restore_claim():
    """These tests write fake answers into real claims. Before the test, check that every real answer
    of the claim is cached (else skip). After the test, read the claim again from the cache, so the
    real entities, findings and loss dates are back in Neo4j."""
    claim_ids = []

    def protect(claim_id):
        try:
            read_claim_from_cache(claim_id)
        except LookupError:
            pytest.skip(f"{claim_id} is not fully cached, so it cannot be restored. Run: python main.py "
                        f"ingest-documents --entities --findings --claim-ids {claim_id}")
        claim_ids.append(claim_id)

    yield protect
    for claim_id in claim_ids:
        read_claim_from_cache(claim_id)


def page_of(prompt):
    return prompt.split("<page>\n", 1)[1].split("\n</page>", 1)[0]


def fake_entities_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
    """Lists only the loss date, copied from the page after 'Crash date:' or 'Date of loss:'."""
    match = re.search(r"(Crash date:|Date of loss:)\s*\n?\s*([^\n]+)", page_of(user_prompt))
    if match is None:
        return "{}"
    return json.dumps({"loss_dates": [{"date": match.group(2).strip(), "words_before": match.group(1)}]})


def document_properties(document_id):
    driver = open_neo4j_driver()
    try:
        records, _, _ = driver.execute_query(
            "MATCH (document:Document {document_id: $document_id}) RETURN document.loss_date_in_pdf AS in_pdf, "
            "document.loss_date_page_number AS page, document.loss_date_conflict AS conflict", document_id=document_id)
    finally:
        driver.close()
    return records[0]


def test_documents_store_the_loss_date_and_the_planted_conflict(truth, monkeypatch, restore_claim):
    conflict_claim = sorted(claim_id for claim_id, claim in truth["claims"].items() if claim["loss_date_conflict"])[0]
    restore_claim(conflict_claim)
    monkeypatch.setattr(extraction, "ask_llm", fake_entities_llm)
    intake.read_claim(conflict_claim, read_entities=True, read_findings=False)
    with open(config.PDFS_DIR / "planted_conflicts.csv", encoding="utf-8") as file:
        planted = next(line for line in file if line.startswith(conflict_claim + ","))
    police = document_properties(f"{conflict_claim}-police_report")
    assert police["conflict"] is True and police["page"] == 1
    assert police["in_pdf"].iso_format() == planted.strip().split(",")[-1]       # the planted police date
    fnol = document_properties(f"{conflict_claim}-fnol")
    assert fnol["conflict"] is False and fnol["in_pdf"].iso_format() == planted.split(",")[3]   # the table date
    medical = document_properties(f"{conflict_claim}-medical_records")
    assert medical["in_pdf"] is None and medical["page"] is None and medical["conflict"] is False


def fake_findings_llm(user_prompt, model_name, system_prompt, max_tokens=1500, effort="low"):
    """One real quote from the last long line of the page, plus one invented quote."""
    lines = [line for line in page_of(user_prompt).splitlines() if len(line) > 40]
    if not lines:
        return '{"findings": []}'
    return json.dumps({"findings": [finding("account_stability", "Stable", lines[-1].strip()),
                                    finding("occurrence_support", "Confirmed", "An invented sentence that is nowhere.")]})


def count_findings(document_id):
    driver = open_neo4j_driver()
    try:
        records, _, _ = driver.execute_query(
            "MATCH (claim:Claim)-[:HAS_FINDING]->(finding:Finding)-[:FOUND_IN]->(:Document {document_id: $document_id}) "
            "RETURN count(finding) AS count, collect(finding.note_date)[0] AS note_date, "
            "collect(claim.claim_id)[0] AS claim_id", document_id=document_id)
    finally:
        driver.close()
    return records[0]


def test_findings_are_saved_with_proof_and_a_rerun_replaces_them(truth, monkeypatch, restore_claim):
    claim_id = truth["demo_claims"]["ring"]
    restore_claim(claim_id)
    monkeypatch.setattr(feature_extraction, "ask_llm", fake_findings_llm)
    result = intake.read_claim(claim_id, read_entities=False, read_findings=True)
    notes = f"{claim_id}-adjuster_file"
    saved = count_findings(notes)
    assert saved["count"] == 2 and saved["claim_id"] == claim_id      # one per page; the invented quotes are dropped
    assert saved["note_date"] is not None                             # page 1 holds dated note entries
    notes_dropped = [item for item in result["dropped_findings"] if item["document_id"] == notes]
    assert [item["reason"] for item in notes_dropped] == ["the quote is not on the page"] * 2

    monkeypatch.setattr(feature_extraction, "ask_llm", lambda *arguments, **keywords: '{"findings": []}')
    intake.read_claim(claim_id, read_entities=False, read_findings=True)
    assert count_findings(notes)["count"] == 0                        # the new reading replaced the old one


def test_bad_llm_output_does_not_crash_the_run(truth, monkeypatch, restore_claim):
    claim_id = truth["demo_claims"]["build_up"]
    restore_claim(claim_id)
    monkeypatch.setattr(feature_extraction, "ask_llm", lambda *arguments, **keywords: "this is not JSON")
    result = intake.read_claim(claim_id, read_entities=False, read_findings=True)
    assert result["findings"] == [] and any("no valid findings JSON" in warning for warning in result["intake_warnings"])
