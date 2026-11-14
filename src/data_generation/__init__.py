"""Code that makes the fake data (tables, ground truth and PDFs). The loaders are in src/data_loading/.

Tables:  generate_tables.py runs, in this order:
         claim_plan_blocks -> plan_fraud_claims + plan_honest_claims -> plan_signals_and_features
         -> write_claim_rows (+ write_policy_and_lawsuit_rows) -> compute_network_truth.
PDFs:    generate_pdfs.py reads the tables and the ground truth, then calls the make_*.py builders.
"""
