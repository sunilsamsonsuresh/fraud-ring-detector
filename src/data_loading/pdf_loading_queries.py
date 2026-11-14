"""The Cypher queries that load the PDFs into the graph. Each query is a named constant.

Values come in as parameters. No query is built by joining strings (CLAUDE.md, rule 5.2).
Facts from a PDF keep their source: the document and the page number (CLAUDE.md, rule 5.6).
"""

# --- Documents and chunks ---------------------------------------------------------------------

# One Document node for each PDF, linked to its claim.
SAVE_DOCUMENT = """
MATCH (claim:Claim {claim_id: $claim_id})
MERGE (document:Document {document_id: $document_id})
SET document.document_type = $document_type, document.file_name = $file_name,
    document.page_count = $page_count
MERGE (claim)-[:HAS_DOCUMENT]->(document)
"""

# One Chunk node for each piece of text, linked to its document. The embedding is a list of 384 numbers.
SAVE_CHUNKS = """
UNWIND $chunks AS chunk
MATCH (document:Document {document_id: chunk.document_id})
MERGE (piece:Chunk {chunk_id: chunk.chunk_id})
SET piece.text = chunk.text, piece.page_number = chunk.page_number,
    piece.chunk_number = chunk.chunk_number, piece.embedding = chunk.embedding
MERGE (document)-[:HAS_CHUNK]->(piece)
"""

# --- Entities that a PDF mentions -------------------------------------------------------------

# The table values of one claim. The entity reader needs the claimant name and the loss date.
CLAIM_FACTS_FOR_PDF_READING = """
MATCH (claimant:Claimant)-[:FILED]->(claim:Claim {claim_id: $claim_id})
RETURN claimant.first_name + " " + claimant.last_name AS claimant_name, claim.loss_date AS loss_date
"""

# elementId(node) is the internal ID of Neo4j for a node. The matching code reads it once, and
# SAVE_MENTIONS uses it to find the node again. A label cannot be a parameter, so this lets ONE
# query link a document to any kind of node.
CLAIMANTS_FOR_MATCHING = """
MATCH (claimant:Claimant)
OPTIONAL MATCH (claimant)-[:HAS_PHONE]->(phone:Phone)
RETURN elementId(claimant) AS element_id, claimant.claimant_id AS node_id,
       claimant.first_name + " " + claimant.last_name AS name,
       claimant.date_of_birth AS date_of_birth, phone.number AS phone_number
"""

NODES_FOR_MATCHING = """
MATCH (node)
WHERE node:Phone OR node:Address OR node:Provider OR node:Attorney OR node:LawFirm
   OR node:Expert OR node:Court OR node:Vehicle OR node:Policy
RETURN elementId(node) AS element_id, labels(node)[0] AS label, properties(node) AS properties
"""

# One MENTIONS edge for each (document, page, node). page_number is part of the MERGE key, so a name on
# page 1 and on page 2 gives two edges, and a second run gives no copies. These edges come from an LLM
# reading, so they are medium trust. They always keep their source.
SAVE_MENTIONS = """
UNWIND $mentions AS mention
MATCH (document:Document {document_id: $document_id})
MATCH (entity) WHERE elementId(entity) = mention.element_id
MERGE (document)-[edge:MENTIONS {page_number: mention.page_number}]->(entity)
SET edge.value_as_written = mention.value_as_written, edge.match_method = mention.match_method,
    edge.source = "llm_extraction"
"""

# Rule AS-7 reads the loss date written in each document. A document with no readable loss date
# gets null, null and false.
SAVE_DOCUMENT_LOSS_DATE = """
MATCH (document:Document {document_id: $document_id})
SET document.loss_date_in_pdf = $loss_date_in_pdf, document.loss_date_page_number = $page_number,
    document.loss_date_conflict = $loss_date_conflict
"""

# --- Findings ---------------------------------------------------------------------------------

# A new reading replaces the old findings of the document (only Finding nodes, only this document).
DELETE_FINDINGS_OF_DOCUMENT = """
MATCH (:Document {document_id: $document_id})<-[:FOUND_IN]-(finding:Finding)
DETACH DELETE finding
"""

SAVE_FINDINGS = """
MATCH (claim:Claim {claim_id: $claim_id})
MATCH (document:Document {document_id: $document_id})
UNWIND $findings AS item
MERGE (finding:Finding {finding_id: item.finding_id})
SET finding.feature = item.feature, finding.value = item.value, finding.severity_rank = item.severity_rank,
    finding.confidence = item.confidence, finding.quote = item.quote, finding.reason = item.reason,
    finding.page_number = item.page_number, finding.note_date = item.note_date,
    finding.document_type = $document_type, finding.source = "llm_extraction"
MERGE (claim)-[:HAS_FINDING]->(finding)
MERGE (finding)-[:FOUND_IN]->(document)
"""
