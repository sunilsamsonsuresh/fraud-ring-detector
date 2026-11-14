# Fraud Ring Detector

A GraphRAG chat for fraud investigators. It works on personal auto injury claims.

The tool puts claims, people, phones, addresses, repair shops, clinics, law firms, lawsuits and the claim documents into one graph database. An investigator asks a question in plain English. A team of AI agents searches the graph and the documents, and gives a short answer with sources.

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

The tool has two parts:

1. **The pipeline** (run one time). It makes fake claims and fake PDF documents, loads them into a graph database (Neo4j), scores every claim with fixed rules, and finds the groups of linked claims (communities).
2. **The chat.** A planner agent reads the question and sends each part to the search agent that fits:

| Agent | Example question | What it does |
|-------|------------------|--------------|
| Local search | "Tell me about David Richardson." | Reads one person, business, phone, address or claim, and everything around it. |
| Document search | "Which claims mention home stretching?" | Searches all documents by meaning and by words, then adds the claim of each hit. |
| Global search | "Are there any fraud rings?" | Reads the communities (groups of linked claims) and their reports. |
| Graph query | "How many claims are in each status?" | Writes one read-only database query. Plain code checks it before it runs. |
| Scorer | "Why is C-1088 High?" | Gets the risk score of a claim from the fixed rules, with the proof. |

An answer writer then writes a short reply from the findings. Plain code checks the reply and adds the sources.

The fake data has 3 hidden fraud rings:

| Ring | Pattern |
|------|---------|
| A | Staged accidents. The claims share phones, addresses and one repair shop. The accident stories are almost the same. |
| B | One clinic and one law firm. The claims have the same treatment pattern and similar medical bills. |
| C | Lawsuits. The claims use the same law firm and the same expert. The lawyers file just before the legal deadline. |

The data also has **innocent overlaps**. Examples: family members who share an address, and a popular repair shop with many honest customers. A good tool must not mark these as fraud.

## 2. Project status

The backend (Phase 1) is complete. A web front end comes next.

| Part | Status |
|------|--------|
| Fake tables (500 claims, 50 lawsuits) and fake PDFs (2,826 documents) | Works |
| Pipeline: tables, PDFs, scores, communities and graph map in Neo4j | Works |
| Chat: planner, 5 search agents, answer writer (LangGraph) | Works, tested with a fake LLM |
| 4 MCP servers with the tools of the agents | Works |
| Test questions with the real LLM (build step 6) | Skipped for now |

## 3. Words used in this README

| Word | Meaning | Example |
|------|---------|---------|
| Graph database | A database that keeps things (**nodes**) and the links between them (**edges**). | The node `Claim C-1037` has an edge to the node `Phone 713-555-3237`. |
| Neo4j | The graph database that this project uses. | You open it in a web browser at `http://localhost:7474`. |
| Cypher | The query language of Neo4j. | `MATCH (c:Claim) RETURN count(c)` counts the claims. |
| Docker | A program that runs other programs in a closed box (a **container**). | Docker runs Neo4j, so you do not install Neo4j yourself. |
| LLM | Large language model. An AI that reads and writes text. This project uses Anthropic Claude. | The LLM wrote the free text in the fake PDFs. |
| Agent | A part of the program that uses an LLM to decide what to do next. Plain code does the work. | The planner chooses which search agent gets a question. |
| MCP | Model Context Protocol: a standard way to offer tools to an AI program. Each MCP server is a small program with a fixed list of tools. | The scorer agent calls the tool `get_claim_score` on the claim records server. |
| GraphRAG | Retrieval-augmented generation over a graph: the LLM answers from what it finds in the graph and the documents. | The answer to "Are there rings?" comes from the communities in the graph. |
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
   python -m pytest -q tests/test_graph_connection.py
   ```
   All tests in the file must pass.

## 6. Use the tool

Start the virtual environment and Neo4j first (setup steps 3 and 7).

### See all commands

```bash
python main.py --help
```

### Make the fake data (optional)

The data is already in the repository (section 8). Make it again only if you want to.

```bash
python main.py generate-data --tables
```

This writes the CSV files to `data/tables/` and the answer key to `data/ground_truth.json`. It uses a fixed random seed (42), so each run makes the same data.

```bash
python main.py generate-data --pdfs --limit 5
```

This makes the PDFs of 5 claims. Remove `--limit 5` to make all of them. The tool asks you to confirm. The PDF text comes from the LLM, but every answer is in `data/cache/`, so the same run costs nothing.

### Build the graph

```bash
python main.py build-graph
```

This runs the pipeline in order: the tables, the PDFs (pages, chunks, mentions, findings), the scores of all claims, the communities, and the graph map. The tool asks you to confirm. You can run it again: every step uses MERGE, so it makes no copies. Add `--write-reports` to let the LLM write one report for each community (cached).

### Look at one score, or at the rules

```bash
python main.py score-claim C-1088
```

```bash
python main.py show-rules
```

### Ask questions in plain English

```bash
python main.py chat
```

Examples: `Are there any fraud rings?`, `Tell me about David Richardson`, then `Why is his top claim High?`.
The chat remembers the conversation until you type `exit`. Each message uses the strong model and costs a few cents.

To see each step of one message (the agent that ran, the tools it called, what it added), run:

```bash
python debug_chat.py "Why is C-1088 High?"
```

It uses the cheap model, so it costs about one cent.

## 7. Run the tests

Start Neo4j first. Then run this command:

```bash
python -m pytest -q -p no:warnings
```

The tests do not call the LLM. They use a fake LLM with scripted answers, so they cost nothing. They use the real graph and the real MCP servers.

**Caution:** the tests read the same Neo4j database as the tool. They do not change it.

Some tests load data into a second, empty Neo4j (the scratch database). They are skipped if it does not run. To start it:

```bash
docker run -d --name fraud-ring-scratch-neo4j -p 7688:7687 -e NEO4J_AUTH=neo4j/scratch-test-password neo4j:5.26-community
```

## 8. The data in this repository

The `data/` folder is in the repository. You can use the project without making the data again.

| Folder or file | What it holds |
|----------------|---------------|
| `data/tables/` | 16 CSV files: claims, claimants, incidents, policies, vehicles, addresses, providers, treatments, attorneys, law firms, lawsuits, settlements, courts, experts, payments, reserve events. |
| `data/pdfs/` | One folder for each claim, with its PDF documents. `documents.csv` lists all PDFs. `planted_conflicts.csv` lists the date errors that we put in on purpose. |
| `data/cache/` | The saved LLM answers. One JSON file for each answer. |
| `data/ground_truth.json` | The answer key: which claims are in each ring, and which claims are innocent overlaps. |
| `data/graph_map.json` | What is in the graph (labels, properties, links). The graph query agent reads it. |

Each PDF page has this text at the bottom: **SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD**.

## 9. Project layout

```
fraud-ring-detector/
  main.py                 Reads the command. Calls one function.
  debug_chat.py           Runs one chat message and prints each step.
  docker-compose.yml      Starts Neo4j.
  requirements.txt        Python packages.
  .env.example            Settings file with fake values. Copy it to .env.
  data/                   Fake data (see section 8).
  src/
    config.py             All settings: model names, folders, seed, limits.
    llm.py                Asks Claude. The pipeline saves each answer in the cache; the chat does not.
    state.py              The shared state of the chat: the messages.
    workflow.py           The LangGraph chat graph: planner -> search agents -> answer writer.
    agents/               The planner, the 5 search agents and the answer writer.
    mcp_servers/          The 4 MCP servers, and the client that the agents use (call_server_tool.py).
    tools/                The plain code behind each tool. checks.py checks every value.
                          query_guard.py checks every generated query.
    scoring/              The facts of a claim, the 32 rules and the score engine.
    graph/                connection.py (Neo4j) and queries.py (all fixed read queries).
    data_generation/      Makes the fake tables and PDFs.
    data_loading/         The pipeline: tables, PDFs, scores, communities, graph map.
  tests/                  Automatic tests (pytest).
```

## 10. Safety rules in the code

- **Agents reach the data only through MCP tools.** Each agent has a fixed list of tools. Each tool checks its values and passes them to a fixed query as parameters. A test sends `MATCH (n) DETACH DELETE n` to every tool. Nothing runs, and the graph does not change.
- **One agent writes its own queries, and they can only read.** The graph query agent writes Cypher. Plain code refuses write words and unknown procedures, Neo4j must confirm with `EXPLAIN` that the query only reads, and the query runs in a read-only session with a time limit and a row limit.
- **Plain code checks every reply.** A reply that names a claim or a rule that no tool returned, or that uses a word like "guilty", is not shown.
- **The score is plain code.** The LLM never decides points and never decides if a rule fires.
- **Passwords and keys stay in `.env`.** The code never prints them.
- **Each pipeline LLM answer goes into the cache.** The same request does not cost money two times.

## 11. If you have a problem

| Problem | What to do |
|---------|------------|
| `Cannot reach Neo4j at bolt://localhost:7687` | Start Neo4j with `docker compose up -d`. Wait 20 seconds. Try again. |
| `Neo4j rejected the user name or password` | Make sure that `NEO4J_PASSWORD` in `.env` is the same as the password when you first started Neo4j. If you changed it, the old password is still in the Docker volume. |
| `ANTHROPIC_API_KEY is empty` | Put your key in `.env`. |
| `data/tables/claims.csv is missing` | Run `python main.py generate-data --tables`. |
| `ModuleNotFoundError` | Start the virtual environment: `source .venv/bin/activate`. |
