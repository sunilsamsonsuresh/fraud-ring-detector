"""The guard in front of a GENERATED query: plain code checks it before it runs. No LLM is called here.

The graph query agent writes its own Cypher query (text-to-Cypher). A query from an LLM is not trusted,
so it must pass these checks, and then it runs in a way that cannot change the graph:

  1. check_generated_query: the text. One statement, no write word, CALL only for the allowed procedures.
  2. find_unknown_properties: every property it reads on a node must exist on that label (the graph map).
  3. check_query_plan: Neo4j itself plans the query (EXPLAIN, nothing runs). It must only read, and every
     label and relationship type must exist in the database.
  4. The caller runs it in a READ session, with a time limit and a row limit (src/tools/query_tools.py).
     In a READ session Neo4j refuses any write, even one that passed the checks before.

Example: "MATCH (c:Claim) RETURN count(c)" passes. "MATCH (n) DETACH DELETE n" stops at check 1.
"MATCH (c:Claim) RETURN avg(c.risk_score)" stops at check 2: a Claim has no risk_score.
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

# "(c:Claim" means: the variable c is a Claim node. "c.risk_score" means: the query reads risk_score of c.
NODE_WITH_LABEL = re.compile(
    r"\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*:\s*([A-Za-z_][A-Za-z0-9_]*)"
)
PROPERTY_READ = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)")

# The codes of the EXPLAIN warnings about names that are not in the database:
# 01N50 an unknown label, 01N51 an unknown relationship type, 01N52 an unknown property name.
UNKNOWN_NAME_WARNINGS = ["01N50", "01N51", "01N52"]


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


def find_unknown_properties(query, graph_map):
    """Return None when every property the query reads exists on its node label, else a message.

    Example: in "MATCH (c:Claim) RETURN avg(c.risk_score)", c is a Claim, and the graph map says that a Claim
    has no risk_score (the scores are on ScoreSnapshot). Neo4j would give null without an error, so the agent
    would read empty rows. A variable with no label in the query (c AFTER "WITH head(...) AS c") is not checked."""
    properties_of_label = {}
    for node in graph_map["nodes"]:
        properties_of_label[node["label"]] = node["properties"]
    label_of_variable = {}
    for variable, label in NODE_WITH_LABEL.findall(query):
        label_of_variable[variable] = label

    unknown = []
    labels_with_unknown = []
    for variable, property_name in PROPERTY_READ.findall(query):
        label = label_of_variable.get(variable)
        if label not in properties_of_label:
            continue  # no label, or a label that is not in the map (EXPLAIN checks labels)
        if property_name not in properties_of_label[label]:
            text = f"{label} has no property '{property_name}'"
            if text not in unknown:
                unknown.append(text)
            if label not in labels_with_unknown:
                labels_with_unknown.append(label)
    if not unknown:
        return None
    message = "The graph map shows: " + "; ".join(unknown) + "."
    for label in labels_with_unknown:
        message += f" A {label} has: {', '.join(properties_of_label[label])}."
    return message


def check_query_plan(session, query):
    """Ask Neo4j for the plan of the query (EXPLAIN runs nothing). Return None if it is fine, else a message.

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
    # A misspelt label or relationship type is not an error in Cypher: the query only finds nothing.
    # EXPLAIN warns about it, so we refuse the query and pass the warning on to the agent.
    unknown_names = []
    for status in summary.gql_status_objects:
        if status.gql_status in UNKNOWN_NAME_WARNINGS:
            unknown_names.append(status.status_description)
    if unknown_names:
        return (
            "Neo4j says: "
            + " ".join(unknown_names)
            + " Use the names of the graph map."
        )
    return None
