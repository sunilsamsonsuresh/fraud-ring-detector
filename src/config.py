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
