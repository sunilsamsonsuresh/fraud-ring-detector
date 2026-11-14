"""The guard in front of a GENERATED query: plain code checks it before it runs. No LLM is called here.

The graph query agent writes its own Cypher query (text-to-Cypher). A query from an LLM is not trusted,
so it must pass three checks, and then it runs in a way that cannot change the graph:

  1. check_generated_query: the text. One statement, no write word, CALL only for the allowed procedures.
  2. check_plan_is_read_only: Neo4j itself plans the query (EXPLAIN, nothing runs) and says if it reads only.
  3. The caller runs it in a READ session, with a time limit and a row limit (src/tools/query_tools.py).
     In a READ session Neo4j refuses any write, even one that passed 1 and 2.

Example: "MATCH (c:Claim) RETURN count(c)" passes. "MATCH (n) DETACH DELETE n" stops at check 1.
A refused query gives a clear message, so the agent can fix it and try again.
"""

import re

from neo4j.exceptions import Neo4jError

MAX_QUERY_CHARACTERS = 2000

# Words that change the graph or the database. \b in the pattern below means a whole word, so the
# property "settlement_amount" does not match "SET". Text in quotes is also checked: a name like 'Set'
# is refused too. That is rare, and safe.
REFUSED_WORDS = [
    "CREATE",
    "MERGE",
    "SET",
    "DELETE",
    "DETACH",
    "REMOVE",
    "DROP",
    "FOREACH",
    "LOAD",
    "INSERT",
    "ALTER",
    "GRANT",
    "DENY",
    "REVOKE",
    "TERMINATE",
    "START",
    "STOP",
    "USE",
]

# The only procedures a generated query may CALL. They search the two chunk indexes and only read.
ALLOWED_PROCEDURES = ["db.index.vector.queryNodes", "db.index.fulltext.queryNodes"]

# The first word of a read query.
ALLOWED_FIRST_WORDS = ["MATCH", "OPTIONAL", "WITH", "UNWIND", "RETURN", "CALL"]


def check_generated_query(text):
    """Return (query, None) when the text looks like ONE read-only query, else (None, a message)."""
    if not isinstance(text, str) or not text.strip():
        return None, "The query is empty."
    query = text.strip()
    if query.endswith(";"):
        query = query[:-1].strip()
    if len(query) > MAX_QUERY_CHARACTERS:
        return None, f"The query is longer than {MAX_QUERY_CHARACTERS} characters."
    if ";" in query:
        return None, "Send one query only (no ';' inside it)."

    first_word = query.split()[0].upper()
    if first_word not in ALLOWED_FIRST_WORDS:
        return None, (
            f"A query must start with one of: {', '.join(ALLOWED_FIRST_WORDS)}. "
            f"This one starts with '{first_word[:20]}'."
        )

    for word in REFUSED_WORDS:
        if re.search(r"\b" + word + r"\b", query, re.IGNORECASE):
            return None, f"The word {word} is not allowed: the query must only read."

    # CALL { ... } runs a subquery. CALL name(...) runs a procedure. Only the allowed procedures may run.
    if re.search(r"\bCALL\s*\{", query, re.IGNORECASE):
        return None, "CALL { ... } subqueries are not allowed."
    for procedure in re.findall(r"\bCALL\s+([A-Za-z0-9_.]+)", query, re.IGNORECASE):
        if procedure not in ALLOWED_PROCEDURES:
            return None, (
                f"The procedure {procedure[:60]} is not allowed. "
                f"Allowed: {', '.join(ALLOWED_PROCEDURES)}."
            )
    return query, None


def check_plan_is_read_only(session, query):
    """Ask Neo4j for the plan of the query (EXPLAIN runs nothing). Return None if it only reads, else a message.

    EXPLAIN is put in front of the generated text. This is the one place where query text is joined:
    the text already passed check_generated_query, and EXPLAIN only plans it."""
    try:
        summary = session.run("EXPLAIN " + query).consume()
    except Neo4jError as error:
        # A syntax error or an unknown function: the agent can read the reason and fix the query.
        return f"Neo4j cannot run this query: {str(error.message)[:300]}"
    # query_type: "r" read only, "rw" read and write, "w" write only, "s" schema change.
    if summary.query_type != "r":
        return f"Neo4j says this query is not read-only (type '{summary.query_type}')."
    return None
