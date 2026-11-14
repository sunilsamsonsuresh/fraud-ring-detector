"""Plain-code tool: the saved scores of ALL claims. No LLM is called here and nothing is scored again.

It answers questions with no claim ID, for example "Which claims have the highest score?" or "How many claims are High?".
It reads the newest ScoreSnapshot of each claim (one query, src/graph/queries.py). Plain Python counts and sorts.
The scores are saved values. They are a pointer for a human reviewer. They are not a finding of fraud.
"""

from src import config
from src.graph import queries

BAND_NAMES = [
    band_name for _, band_name, _ in config.BANDS
]  # "Very High", "High", "Medium", "Low"


def list_claims_by_score(driver, band):
    """The band counts of all claims, and the claims with the highest scores (only those in `band`, or all if "any").

    band is checked before (src/tools/checks.py, check_band)."""
    records, _, _ = driver.execute_query(queries.LATEST_SCORE_OF_EVERY_CLAIM)
    all_claims = [record.data() for record in records]
    scored_claims = [claim for claim in all_claims if claim["total_score"] is not None]
    if not scored_claims:
        return {"message": "No claim has a saved score."}

    band_counts = {band_name: 0 for band_name in BAND_NAMES}
    for claim in scored_claims:
        band_counts[claim["band"]] += 1

    matching_claims = [
        claim for claim in scored_claims if band == "any" or claim["band"] == band
    ]
    # Highest score first. The claim ID breaks a tie, so the same data always gives the same list.
    matching_claims.sort(key=lambda claim: (-claim["total_score"], claim["claim_id"]))
    shown_claims = []
    for claim in matching_claims[: config.MAX_CLAIMS_SHOWN_BY_SCORE]:
        shown_claims.append(
            {
                key: claim[key]
                for key in [
                    "claim_id",
                    "total_score",
                    "band",
                    "coverage_pct",
                    "fired_rule_ids",
                ]
            }
        )

    notes = [
        "These are saved scores: the newest snapshot of each claim. Nothing was scored again now.",
        "A score is a pointer for a human reviewer. It is not a finding of fraud.",
    ]
    if len(matching_claims) > len(shown_claims):
        notes.append(
            f"{len(matching_claims)} claims match. The {len(shown_claims)} with the highest scores are shown."
        )
    saved_days = sorted({claim["as_of_date"] for claim in scored_claims})
    return {
        "facts": {
            "band_filter": band,
            "claims_in_graph": len(all_claims),
            "claims_with_saved_score": len(scored_claims),
            "band_counts": band_counts,
            "matching_claim_count": len(matching_claims),
            "top_claims": shown_claims,
            "saved_scores_from": saved_days[0],
            "saved_scores_to": saved_days[-1],
        },
        "notes": notes,
        "sources": ["Newest ScoreSnapshot node of each claim"],
    }
