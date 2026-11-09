"""All project settings in one place.

Secrets and connection values come from the .env file.
Fixed choices (model names, folder paths) are plain constants here.
Other files import from this file. They never hard-code these values.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# The project folder is two levels above this file: src/config.py -> project root.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Read .env into the environment. If .env is missing, nothing breaks here;
# the code that needs a value checks for it and prints a clear message.
load_dotenv(PROJECT_ROOT / ".env")

# --- Neo4j ---
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "")

# --- Anthropic ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

# Cheaper model: data generation, PDF extraction, Question Router.
CHEAP_MODEL_NAME = "claude-haiku-5-5"
# Stronger model: Challenger and Report Writer.
STRONG_MODEL_NAME = "claude-sonnet-5-5"

# --- Embeddings (free local model, used from Step 7) ---
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Each text chunk becomes a list of this many numbers. The Neo4j vector
# index must use the same number, so both values must change together.
EMBEDDING_DIMENSIONS = 384

# --- Fake data ---
# The data generator uses this seed. Same seed gives the same files.
RANDOM_SEED = 42

# --- Folders ---
DATA_DIR = PROJECT_ROOT / "data"
TABLES_DIR = DATA_DIR / "tables"
PDFS_DIR = DATA_DIR / "pdfs"
CACHE_DIR = DATA_DIR / "cache"
GROUND_TRUTH_FILE = DATA_DIR / "ground_truth.json"

# --- Litigation (Step 8, PLAN.md A8). "Near the deadline" uses SUIT_NEAR_DEADLINE_DAYS (CT-7). ---
# Two demands are "similar" when they differ by this share or less (0.03 = 3%).
SIMILAR_DEMAND_SHARE = 0.03
# The v2 total score goes from 0 to this number (A7). The v1 signal weights were removed in V7.
MAX_RISK_SCORE = 100

# --- Challenger and workflow (Step 9, PLAN-v2.md A8) ---
# The Challenger may ask for more evidence once: at most 2 rounds in total (A8, V12).
MAX_INVESTIGATION_LOOPS = 1
REPORTS_DIR = DATA_DIR / "reports"
DECISIONS_FILE = DATA_DIR / "decisions.jsonl"   # V13: one line for each decision of the investigator
MAX_HUMAN_REQUESTS = 1                          # V13: the investigator may ask for more investigation this often

# =====================================================================================
# v2 settings (PLAN-v2.md). All weights, bands and thresholds of the v2 score live here
# (CLAUDE.md, rule 21). They are starting values. V10 tunes them on the tuning split only.
# The v1 settings above stay for the v1 agents until V11 and V12 replace them.
# =====================================================================================

# --- Category weights (A7). They add up to 1. ---
CATEGORY_WEIGHTS = {"BI": 0.25, "AS": 0.25, "BF": 0.15, "CT": 0.15, "NL": 0.20}

# --- Bands and actions (A7). The first row whose minimum the total score reaches wins. ---
BANDS = [
    (30, "Very High", "Refer to the special investigation unit (SIU)."),
    (20, "High", "Assign an investigator."),
    (10, "Medium", "Monitor and score again in 30 days."),
    (0, "Low", "No action."),
]

# --- Rule thresholds (A7). Names say what they measure. ---
HEAVY_EARLY_TREATMENT_VISITS = 12      # BI-6: more than this many visits ...
HEAVY_EARLY_TREATMENT_DAYS = 30        # ... in this many days after the loss date
RESERVE_RISE_SHARE = 0.50              # BF-1: the reserve grows more than 50% ...
RESERVE_RISE_DAYS = 30                 # ... within this many days
PAID_TO_RESERVE_RATIO = 1.5            # BF-2: paid is at least 1.5 times the reserve
PAYMENT_CLUSTER_COUNT = 3              # BF-3: this many payments or more ...
PAYMENT_CLUSTER_DAYS = 14              # ... within this many days
REPAIR_GROWTH_RATIO = 1.5              # BF-4: repair paid is at least 1.5 times the first estimate
NEW_CUSTOMER_DAYS = 30                 # CT-1: loss under this many days after customer_since
COVERAGE_INCREASE_DAYS = 30            # CT-2: loss 0 to this many days after a coverage increase
LATE_REPORT_DAYS = 30                  # CT-4: reported more than this many days after the loss
SUIT_NEAR_DEADLINE_DAYS = 30           # CT-7: suit filed within this many days before the deadline
FILING_DEADLINE_YEARS = 2              # filing_deadline = loss date plus this many years
REPEAT_CLAIM_OTHER_CLAIMS = 2          # NL-2: the claimant has this many other claims or more ...
REPEAT_CLAIM_MONTHS = 36               # ... within this many months
CLINIC_AND_ATTORNEY_MIN_CLAIMS = 5     # NL-3: strong link (c) to this many claims or more
FIRM_AND_EXPERT_MIN_LAWSUITS = 3       # NL-5: strong link (d) to this many lawsuits or more ...
FIRM_AND_EXPERT_MONTHS = 12            # ... within this many months
SIMILARITY_THRESHOLD = 0.985           # NL-4: story chunk similarity (Neo4j cosine, 0 to 1)
# NL-4 compares only the claimant's story and the legal wording. Forms and tables look alike by
# design. Medical treatment summaries were removed in V8: across the whole portfolio their LLM
# boilerplate reached 0.995 between unrelated claims (728 false pairs, 0 real copies).
STORY_DOCUMENT_TYPES = ["fnol", "complaint", "demand_letter"]
CLUSTER_MIN_CLAIMS = 8                 # NL-6: a group of this many claims or more ...
CLUSTER_MAX_HOPS = 3                   # ... joined by strong links, up to this many hops

# --- Score history (V9). Starting values. ---
TREND_DAYS = 90                        # the trend compares the latest score with the score this many days earlier
TREND_MIN_CHANGE = 2.0                 # a change of at least this many points is "rising" or "declining"

# --- Findings and the Challenger (A6, A8) ---
CONFIDENCE_LEVELS = ["Low", "Medium", "High"]
MIN_CONFIDENCE = "Medium"              # a finding below this is saved but fires no rule
BUSY_PROVIDER_LIMIT = 20               # a provider with more claims than this is "busy"
COMMON_RULE_SHARE = 0.25               # Challenger note: the rule fires on more than this share of claims
LOW_COVERAGE_PCT = 60                  # Challenger note below this coverage: "not fully examined"

# --- Fake data v2 (A4). The size is one setting. ---
TOTAL_CLAIMS = 500
TOTAL_LAWSUITS = 50
# Planted fraud: claims per fraud type (about 12% of all claims).
FRAUD_TYPE_SIZES = {"ring_a": 10, "ring_b": 14, "ring_c": 11, "build_up": 5, "jump_in": 5,
                    "billing_inflation": 5, "coverage_trigger": 5, "paper_accident": 5}
# Lookalikes: honest claims that look like fraud on purpose (at least 100 claims).
FAMILY_PAIRS = 8                                       # pairs: shared address and phone, different incidents
MULTI_CLAIMANT_INCIDENT_SIZES = [2, 3, 4, 2, 3, 2, 4, 3, 2, 3]   # honest incidents, claimants in each
LOOKALIKE_GROUP_SIZES = {"busy_law_firm": 25, "busy_repair_shop": 25, "large_clinic": 25,
                         "late_reporter": 15, "new_customer": 10, "serious_injury": 10,
                         "pre_existing": 10}
BUSY_LAW_FIRM_LAWSUITS = 6

# Profile of each fraud type: rule ID -> the chance that ONE claim of this type shows the
# signal (70% to 90%, A4). A claim never shows every signal; some show few. On purpose.
# Proposed in V3 before any data existed. Do not change it to make results look better.
FRAUD_PROFILES = {
    "ring_a": {"AS-5": 0.75, "AS-6": 0.80, "BF-4": 0.80, "NL-1": 0.90, "NL-4": 0.85},
    "ring_b": {"BI-2": 0.80, "BI-3": 0.70, "BI-5": 0.75, "BI-6": 0.80, "NL-3": 0.90},
    "ring_c": {"CT-7": 0.85, "NL-4": 0.80, "NL-5": 0.90},
    "build_up": {"BI-2": 0.90, "BI-3": 0.70, "BI-6": 0.75, "BF-1": 0.75},
    "jump_in": {"AS-5": 0.90, "AS-6": 0.80, "BI-1": 0.70},
    "billing_inflation": {"BF-3": 0.70, "BF-4": 0.80, "BF-5": 0.85, "BF-6": 0.80},
    "coverage_trigger": {"CT-1": 0.75, "CT-2": 0.70, "CT-3": 0.70, "CT-5": 0.80},
    "paper_accident": {"AS-2": 0.80, "AS-3": 0.70, "AS-4": 0.80, "AS-7": 0.75},
}

# --- Base rates: how often each rule fires on ordinary honest claims (A4) ---
# The share of ORDINARY honest claims (not fraud, not in a lookalike group) where the rule
# fires, among the claims where the rule can apply (BI-5: claims with an attorney; BF-4 and
# BF-6: claims with a repair; AS-6 and AS-7: claims with a police report; CT-7 and NL-5:
# claims with a lawsuit). Proposed in V3 before any data existed.
# Nobody changes it later to make the results look better.
HONEST_RULE_RATES = {
    "BI-1": 0.03, "BI-2": 0.05, "BI-3": 0.10, "BI-4": 0.08, "BI-5": 0.08, "BI-6": 0.05,
    "AS-1": 0.06, "AS-2": 0.02, "AS-3": 0.03, "AS-4": 0.04, "AS-5": 0.02, "AS-6": 0.02, "AS-7": 0.05,
    "BF-1": 0.06, "BF-2": 0.03, "BF-3": 0.05, "BF-4": 0.06, "BF-5": 0.03, "BF-6": 0.05,
    "CT-1": 0.03, "CT-2": 0.03, "CT-3": 0.02, "CT-4": 0.06, "CT-5": 0.04, "CT-6": 0.03, "CT-7": 0.06,
    "NL-1": 0.05, "NL-2": 0.03, "NL-3": 0.03, "NL-4": 0.03, "NL-5": 0.12, "NL-6": 0.03,
}
