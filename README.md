# Fraud Ring Detector

A command-line tool that finds possible fraud rings in car insurance injury claims.

The tool puts claims, people, phones, addresses, repair shops, clinics, law firms and lawsuits into a graph database. Then an AI agent looks for claims that share these things.

> **All data in this project is fake.** A program made every name, claim and document. No record is about a real person or a real company.

> **The tool does not say that a person is guilty.** It shows possible links and unusual patterns. A human investigator must review each result.

---

## Contents

1. [What the tool does](#1-what-the-tool-does)
2. [Project status](#2-project-status)
3. [Words used in this README](#3-words-used-in-this-readme)
4. [What you need](#4-what-you-need)
5. [Set up the project](#5-set-up-the-project)
6. [Use the tool](#6-use-the-tool)
7. [Run the tests](#7-run-the-tests)
8. [The data in this repository](#8-the-data-in-this-repository)
9. [Project layout](#9-project-layout)
10. [Safety rules in the code](#10-safety-rules-in-the-code)
11. [If you have a problem](#11-if-you-have-a-problem)

---

## 1. What the tool does

Fraud rings often use the same phone numbers, addresses, repair shops, clinics or lawyers again and again. One claim alone can look normal. Many claims together can show a pattern.

The tool does these steps:

1. It makes fake claims, and fake documents for each claim (PDF files).
2. It loads the claims into a graph database (Neo4j).
3. An AI agent starts from one claim. It finds the other claims that share something with that claim.

Example: claim `C-1037` uses the phone number `713-555-3237`. Three other claims use the same phone number. The agent finds these three claims and shows the shared phone number as the reason.

The fake data has 3 hidden fraud rings:

| Ring | Pattern |
|------|---------|
| A | Staged accidents. The claims share phones, addresses and one repair shop. The accident stories are almost the same. |
| B | One clinic and one law firm. The claims have the same treatment pattern and similar medical bills. |
| C | Lawsuits. The claims use the same law firm and the same expert. The lawyers file just before the legal deadline. |

The data also has **innocent overlaps**. Examples: family members who share an address, and a popular repair shop with many honest customers. A good tool must not mark these as fraud.

## 2. Project status

The project is not finished. These parts work now:

| Part | Status |
|------|--------|
| Neo4j database in Docker | Works |
| Graph design (rules for unique IDs, search indexes) | Works |
| Fake tables: 500 claims, 50 lawsuits | Works |
| Fake PDFs: 2,821 documents | Works |
| Load the tables into Neo4j | Works |
| Agent 2: Graph Investigator | Works |
| Read the PDFs into the graph, search the text, risk score, reports, questions in plain English | Not started |

## 3. Words used in this README

| Word | Meaning | Example |
|------|---------|---------|
| Graph database | A database that keeps things (**nodes**) and the links between them (**edges**). | The node `Claim C-1037` has an edge to the node `Phone 713-555-3237`. |
| Neo4j | The graph database that this project uses. | You open it in a web browser at `http://localhost:7474`. |
| Cypher | The query language of Neo4j. | `MATCH (c:Claim) RETURN count(c)` counts the claims. |
| Docker | A program that runs other programs in a closed box (a **container**). | Docker runs Neo4j, so you do not install Neo4j yourself. |
| LLM | Large language model. An AI that reads and writes text. This project uses Anthropic Claude. | The LLM wrote the free text in the fake PDFs. |
| Agent | A part of the program that uses an LLM to make one decision. Plain code does the work. | The Graph Investigator agent chooses which searches to run. |
| Virtual environment | A folder that keeps the Python packages of one project apart from other projects. | The folder `.venv`. |
| `.env` file | A private file that keeps passwords and keys. You do not share it. | `NEO4J_PASSWORD=...` |

## 4. What you need

- A Mac, Linux or Windows computer.
- **Python 3.14.** Other Python 3 versions can also work, but we tested only 3.14.
- **Docker Desktop.** Neo4j runs in Docker.
- **An Anthropic API key.** You need it only to make new LLM text. Each LLM call costs money. See [section 8](#8-the-data-in-this-repository).
- About 3 GB of free disk space.

## 5. Set up the project

Do the steps that follow one time.

1. Get the code.
   ```bash
   git clone https://github.com/sunilsamsonsuresh/fraud-ring-detector.git
   cd fraud-ring-detector
   ```
2. Make a virtual environment.
   ```bash
   python3 -m venv .venv
   ```
3. Start the virtual environment. Do this step each time that you open a new terminal.
   ```bash
   source .venv/bin/activate
   ```
   On Windows, use this command: `.venv\Scripts\activate`
4. Install the Python packages.
   ```bash
   pip install -r requirements.txt
   ```
   Note: `sentence-transformers` is large. The install can take some minutes.
5. Make your private settings file.
   ```bash
   cp .env.example .env
   ```
6. Open `.env` in a text editor. Change these two values:
   - `NEO4J_PASSWORD`: write a new password. Use 8 characters or more.
   - `ANTHROPIC_API_KEY`: write your own key. If you do not have a key, keep the fake value.

   **Do not share `.env`. Do not commit it to git.** The `.gitignore` file keeps it out of git.
7. Start Neo4j.
   ```bash
   docker compose up -d
   ```
8. Wait about 20 seconds. Then make sure that Neo4j works.
   ```bash
   python -m pytest -q tests/test_connection.py
   ```
   The result must show `1 passed`.

## 6. Use the tool

Start the virtual environment and Neo4j first (setup steps 3 and 7).

### See all commands

```bash
python main.py --help
```

### Make the fake tables

```bash
python main.py generate-data --tables
```

This command writes CSV files to `data/tables/` and the answer key to `data/ground_truth.json`. It uses a fixed random seed (42). Each run makes the same data.

### Make the fake PDFs

Try 5 claims first:

```bash
python main.py generate-data --pdfs --limit 5
```

To make the PDFs for all claims, remove `--limit 5`. The tool asks you to confirm. Use `--workers 8` to work on 8 claims at the same time.

**Cost warning:** the full run makes about 2,800 LLM calls. Our run cost about USD 0.64. The tool keeps each answer in `data/cache/`. If an answer is in the cache, the tool uses it again and does not pay again.

### Load the data into Neo4j

```bash
python main.py load-graph
```

The command prints the number of nodes and edges. You can run it two times. The second run does not make copies.

### Look at the graph in your browser

1. Open `http://localhost:7474`.
2. Log in with the user and password from your `.env` file.
3. Paste this query. Then push **Ctrl+Enter**. The query finds phone numbers that more than one claim uses.
   ```cypher
   MATCH (phone:Phone)<-[:HAS_PHONE]-(claimant:Claimant)-[:FILED]->(claim:Claim)
   WITH phone, collect(claim.claim_id) AS claim_ids, collect(DISTINCT claimant.last_name) AS last_names
   WHERE size(claim_ids) > 1
   RETURN phone.number AS phone, size(claim_ids) AS claims, claim_ids, last_names
   ORDER BY claims DESC
   ```
4. Look at the result. Each of the top 3 phones links 4 claims with 4 different last names. This is Ring A. The phones below them have one last name each. These are families.

### Run the Graph Investigator agent on one claim

```bash
python -m src.agents.graph_investigator C-1037
```

The agent does these steps:

1. It reads a short profile of the claim from Neo4j.
2. It asks the LLM which searches to run. The LLM can choose only from a fixed list.
3. Plain Python code checks the choice. Then it runs the searches.
4. It prints each linked claim and the reason for the link.

This command makes one LLM call (less than USD 0.01). The claims `C-1037`, `C-1003` and `C-1006` are already in the cache.

## 7. Run the tests

Start Neo4j first. Then run this command:

```bash
python -m pytest -q -p no:warnings
```

The tests do not call the LLM. They use a fake LLM, so they cost nothing.

**Caution:** the tests use the same Neo4j database as the tool. They load the tables into it. They do not delete data.

## 8. The data in this repository

The `data/` folder is in the repository. You can use the project without making the data again.

| Folder or file | What it holds |
|----------------|---------------|
| `data/tables/` | 13 CSV files: claims, claimants, policies, vehicles, addresses, providers, attorneys, law firms, lawsuits, settlements, courts, experts, payments. |
| `data/pdfs/` | One folder for each claim, with its PDF documents. `documents.csv` lists all PDFs. `planted_conflicts.csv` lists the date errors that we put in on purpose. |
| `data/cache/` | The saved LLM answers. One JSON file for each answer. |
| `data/ground_truth.json` | The answer key: which claims are in each ring, and which claims are innocent overlaps. |

Each PDF page has this text at the bottom: **SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD**.

## 9. Project layout

```
fraud-ring-detector/
  main.py                 Reads the command. Calls one function.
  docker-compose.yml      Starts Neo4j.
  requirements.txt        Python packages.
  .env.example            Settings file with fake values. Copy it to .env.
  data/                   Fake data (see section 8).
  src/
    config.py             All settings: model names, folders, seed.
    llm.py                Asks Claude. Saves each answer in the cache.
    state.py              The shared data that the agents pass along.
    datagen/              Makes the fake tables and PDFs.
    graph/
      connection.py       Opens the connection to Neo4j.
      schema.py           Makes the unique-ID rules and the indexes.
      queries.py          ALL Cypher queries, as named constants.
      loader.py           Loads the CSV files into Neo4j.
      investigation.py    The fixed list of searches, and the code that runs them.
    agents/
      graph_investigator.py   Agent 2: finds linked claims.
  tests/                  Automatic tests (pytest).
```

## 10. Safety rules in the code

- **The LLM never writes database queries.** The agent can only choose a search name from a fixed list. Plain code checks the name before it runs anything. A test sends `MATCH (n) DETACH DELETE n` as a choice. The code refuses it, and the graph does not change.
- **All values go into queries as parameters.** The code never makes a query by joining text.
- **Passwords and keys stay in `.env`.** The code never prints them.
- **Each LLM answer goes into the cache.** The same request does not cost money two times.

## 11. If you have a problem

| Problem | What to do |
|---------|------------|
| `Cannot reach Neo4j at bolt://localhost:7687` | Start Neo4j with `docker compose up -d`. Wait 20 seconds. Try again. |
| `Neo4j rejected the user name or password` | Make sure that `NEO4J_PASSWORD` in `.env` is the same as the password when you first started Neo4j. If you changed it, the old password is still in the Docker volume. |
| `ANTHROPIC_API_KEY is empty` | Put your key in `.env`. |
| `data/tables/claims.csv is missing` | Run `python main.py generate-data --tables`. |
| `ModuleNotFoundError` | Start the virtual environment: `source .venv/bin/activate`. |
