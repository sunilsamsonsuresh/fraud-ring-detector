"""The MCP servers of the new system. They offer the plain-code tools of src/tools/ to agents.

claim_records_server.py   get_claim_record, get_claim_score       (one claim: stored data, and the score)
graph_links_server.py     get_claim_neighbourhood, find_claims_sharing_phone, find_claims_linked_to_name
document_search_server.py search_claim_documents                  (text search in the PDFs of one claim)
server_helpers.py         the code that all three servers share
call_server_tool.py       a small client: starts a server, calls a tool, prints the answer
"""
