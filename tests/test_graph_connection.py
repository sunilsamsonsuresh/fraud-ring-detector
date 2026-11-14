"""Tests of src/graph/connection.py (new system). They need Neo4j to run (docker compose up -d)."""

import pytest

from src import config
from src.graph.connection import open_neo4j_driver


def test_a_good_connection_can_run_a_query():
    driver = open_neo4j_driver()
    try:
        records, _, _ = driver.execute_query("RETURN 1 AS one")
    finally:
        driver.close()
    assert records[0]["one"] == 1


def test_an_empty_password_gives_a_clear_message(monkeypatch):
    monkeypatch.setattr(config, "NEO4J_PASSWORD", "")
    with pytest.raises(RuntimeError, match="NEO4J_PASSWORD is empty"):
        open_neo4j_driver()


def test_a_wrong_password_gives_a_clear_message(monkeypatch):
    monkeypatch.setattr(config, "NEO4J_PASSWORD", "this-is-not-the-password")
    with pytest.raises(RuntimeError, match="rejected the user name or password"):
        open_neo4j_driver()


def test_neo4j_not_running_gives_a_clear_message(monkeypatch):
    monkeypatch.setattr(
        config, "NEO4J_URI", "bolt://localhost:1"
    )  # nothing listens on port 1
    with pytest.raises(RuntimeError, match="Cannot reach Neo4j"):
        open_neo4j_driver()
