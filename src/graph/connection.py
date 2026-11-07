"""Open a connection to Neo4j.

Every other file gets its Neo4j driver from open_neo4j_driver().
The driver is the object that sends Cypher queries to the database.
"""

from neo4j import Driver, GraphDatabase
from neo4j.exceptions import AuthError, ServiceUnavailable

from src import config


def open_neo4j_driver() -> Driver:
    """Return a driver that is connected to Neo4j.

    Raises RuntimeError with a clear message if Neo4j cannot be used.
    The caller must close the driver when it is done: driver.close().
    """
    if not config.NEO4J_PASSWORD:
        raise RuntimeError(
            "NEO4J_PASSWORD is empty. Copy .env.example to .env and set the password."
        )

    driver = GraphDatabase.driver(
        config.NEO4J_URI,
        auth=(config.NEO4J_USER, config.NEO4J_PASSWORD),
    )

    # GraphDatabase.driver() does not connect yet. verify_connectivity() does,
    # so we find a problem here and not later in the middle of a query.
    try:
        driver.verify_connectivity()
    except ServiceUnavailable:
        driver.close()
        raise RuntimeError(
            f"Cannot reach Neo4j at {config.NEO4J_URI}. "
            "Is it running? Start it with: docker compose up -d"
        )
    except AuthError:
        driver.close()
        raise RuntimeError(
            "Neo4j rejected the user name or password. "
            "Check NEO4J_USER and NEO4J_PASSWORD in .env."
        )

    return driver
