# Data Firefighter

**Autonomous data incident response, built on DataHub's context graph.**

When a column disappears from a dataset, Data Firefighter investigates the
blast radius, finds the root cause, proposes a fix grounded in the actual
affected code, and opens a real GitHub PR — pausing for human approval
before it touches anything.

Built for **Build with DataHub: The Agent Hackathon**.

---

## Problem

A schema change on one dataset silently breaks every pipeline, dashboard,
and ML model downstream of it. Today, finding out what broke and why is a
manual, multi-tool investigation. Data Firefighter automates that
investigation end-to-end using DataHub as its context graph — not a search
box the agent occasionally queries, but the actual source of lineage,
schema, and ownership it reasons over.

## Solution

An 11-node [LangGraph](https://langchain-ai.github.io/langgraph/) agent:

```
detect_incident → fetch_context → trace_lineage → analyze_blast_radius →
identify_owners → investigate_root_cause → generate_fix → validate_fix →
create_pull_request → write_incident_report → write_back_to_datahub
```

The graph is **human-checkpointed, not fully autonomous**: it investigates
and proposes a fix on its own, but pauses for explicit approval before it
ever touches GitHub. This mirrors the hackathon brief's own principle that
PR creation — not direct production changes — should be the agent's
default action.

## Why DataHub

DataHub is the agent's context graph at every stage:

- **Schema** — `get_dataset`/`get_schema` read the incident dataset's real
  schema (DataHub's `schemaMetadata` aspect) to know exactly what changed.
- **Lineage** — `get_lineage` traces every downstream pipeline, dashboard,
  and ML model affected via DataHub's lineage graph — the blast radius is
  *calculated* from real graph traversal, never hardcoded.
- **Ownership** — `get_owners` resolves the real CorpGroup/CorpUser owner
  of each asset from DataHub's `ownership` aspect, so the right teams are
  identified, not guessed.
- **Root cause** — cross-references DataHub's lineage graph against a live
  GitHub code search: a file only counts as "affected" if it's *both*
  downstream of the incident dataset in DataHub *and* actually references
  the deleted column in the real repo — two independent signals
  corroborating each other, not either alone.
- **Write-back** — resolved incidents get written back to DataHub
  (`updateDescription`, gated behind `DATAHUB_MUTATION_ENABLED` and the
  server's own `TOOLS_IS_MUTATION_ENABLED`), so the next agent or engineer
  inherits the investigation instead of repeating it.

### `DATAHUB_MODE=real` vs. `DATAHUB_MODE=mock`

`DATAHUB_MODE` selects which of two real implementations of the same
`DataHubClient` interface the agent uses — **there is no silent fallback
between them**: if `DATAHUB_MODE=real` and DataHub is unreachable, the
incident fails with an explicit error (`DataHub unreachable... Check
DATAHUB_GMS_URL, or try DATAHUB_MODE=mock`); it never quietly serves mock
data instead.

- **`real`** — `RealDataHubClient` (`app/datahub/real.py`) makes actual
  GraphQL calls against a running DataHub GMS instance for every bullet
  above. Query shapes were verified against DataHub's real GraphQL SDL
  (`datahub-graphql-core/entity.graphql` on GitHub), not guessed.
- **`mock`** (default) — `MockDataHubClient` (`app/datahub/mock.py`) is a
  deterministic demo adapter implementing the identical interface against
  fixture data in `examples/incidents/customer_email_deletion/`. It exists
  so the demo never depends on infrastructure being up, and switching to
  `real` requires only an env var — zero code changes anywhere else in
  the app.

**The recorded demo runs in `DATAHUB_MODE=mock`.** Local DataHub Quickstart
(the official `docker compose` stack) was attempted twice and failed both
times on Docker Hub image-pull failures — a `TLS handshake timeout`
downloading `acryldata/datahub-actions` — not a bug in this project's
DataHub integration. `RealDataHubClient` has real, unit-tested query logic
(`apps/api/tests/test_datahub_real.py`, mocked GraphQL responses) but has
not been exercised against a live GMS instance as part of this submission.

## Architecture

```
data-firefighter/
├── apps/
│   ├── api/                  # FastAPI + LangGraph backend
│   │   └── app/
│   │       ├── api/          # 7 endpoints, mapped to graph checkpoints
│   │       ├── agents/       # graph.py, nodes.py, llm.py, sql_fix.py
│   │       ├── datahub/      # DataHubClient: mock + real, same interface
│   │       ├── github/       # GitHubService (scoped to one demo repo)
│   │       └── incidents/    # IncidentState
│   └── web/                  # Next.js single-page dashboard
├── examples/incidents/customer_email_deletion/
│                              # single source of truth: the SQL fixtures
│                              # here back BOTH the mock DataHub client
│                              # and the seeded demo GitHub repo
└── TODOS.md                  # deliberately deferred scope, with context
```

## Agent workflow

Three checkpoints, mapped onto three API calls a human explicitly triggers:

| Endpoint | Nodes run | What it does |
|---|---|---|
| `POST /api/incidents/demo` | `detect_incident` | Starts the incident |
| `POST /api/incidents/{id}/investigate` | `fetch_context` … `investigate_root_cause` | Reads DataHub, traces lineage, computes blast radius, grounds root cause in real code search |
| `POST /api/incidents/{id}/remediate` | `generate_fix`, `validate_fix` | Proposes a fix (SQL transform, not LLM-freehand), validates it — **does not touch GitHub yet** |
| `POST /api/incidents/{id}/create-pr` | `create_pull_request` … `write_back_to_datahub` | The approval checkpoint: only after this call does anything write to GitHub or DataHub |

State persists across these calls via LangGraph's `AsyncSqliteSaver`
checkpointer, keyed by `thread_id=incident_id`.

## Demo

1. Open the dashboard, click **Column Deleted** under Simulate Incident.
2. Investigation runs automatically (read-only — no writes) and shows the
   real blast radius: downstream pipelines, dashboards, an ML model, and
   the teams that own them.
3. Click **Generate Fix** — review the real before/after SQL diff and
   validation checklist.
4. Click **Approve & Create PR** — a real branch, commit, and PR land on
   your configured GitHub repo. The incident resolves; DataHub write-back
   is attempted (visibly marked if disabled, never faked).

## Tech stack

- **Backend:** Python, FastAPI, LangGraph, Pydantic, `sqlglot`
- **Frontend:** Next.js, TypeScript, Tailwind CSS
- **LLM:** OpenAI or Anthropic, switched via `LLM_PROVIDER`
- **Persistence:** LangGraph `AsyncSqliteSaver` (no Postgres/SQLAlchemy in
  this build — see `TODOS.md` for why and what it'd take to add)

## Setup

### 1. Backend

```bash
cd apps/api
cp ../../.env.example .env   # fill in the values below
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd apps/web
cp .env.local.example .env.local
npm install
npm run dev
```

Next.js picks the next free port if 3000 is taken — check the terminal
output for the actual URL, and update `FRONTEND_ORIGINS` in the backend's
`.env` (comma-separated) if you're not on 3000/3001/3002.

### 3. Environment variables

| Variable | Required | Notes |
|---|---|---|
| `LLM_PROVIDER` | yes | `openai` or `anthropic` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | yes (one) | matching your provider |
| `DATAHUB_MODE` | no | `mock` (default) or `real` |
| `DATAHUB_GMS_URL` / `DATAHUB_GMS_TOKEN` | only if `DATAHUB_MODE=real` | |
| `DATAHUB_MUTATION_ENABLED` | no | app-side write-back gate; the DataHub MCP server's own `TOOLS_IS_MUTATION_ENABLED` must **also** be `true` for a real write to land |
| `GITHUB_TOKEN` | **yes** | needed even in `DATAHUB_MODE=mock` — the agent always searches/PRs against a real repo |
| `GITHUB_DEMO_REPO` | **yes** | `owner/repo` — a throwaway repo you control, seeded with the files in `examples/incidents/customer_email_deletion/` |

### 4. DataHub setup

Default mode (`DATAHUB_MODE=mock`) needs no DataHub instance — the agent
runs against realistic fixture data through the exact same `DataHubClient`
interface a real instance would use, and this is what the recorded demo
uses (see "Why DataHub" above for exactly why).

To run against a real instance:

```bash
uv tool install acryl-datahub
datahub docker quickstart   # official DataHub quickstart
```

Then set `DATAHUB_MODE=real`, `DATAHUB_GMS_URL=http://localhost:8080`, and
a personal access token as `DATAHUB_GMS_TOKEN`. `scripts/seed_datahub.py`
seeds the same customer_email_deletion scenario into a running instance
via DataHub's real Python SDK emitter (not by loading the fixture into the
mock adapter):

```bash
uv run --with acryl-datahub python3 scripts/seed_datahub.py --gms-url http://localhost:8080
```

Note: Quickstart downloads several GB of Docker images (mysql, opensearch,
kafka, and DataHub's own services) — an unreliable network connection to
Docker Hub can cause it to fail on large image pulls, which is what
happened during this submission's development (see "Why DataHub" above).

### 5. GitHub setup

1. Create a throwaway repo (e.g. `you/data-firefighter-demo`).
2. Copy the `.sql` files from `examples/incidents/customer_email_deletion/`
   into it and push. **Wait 1-2 minutes** before running the demo — GitHub's
   code search index has real propagation lag after a push.
3. Set `GITHUB_TOKEN` (a personal access token with repo scope) and
   `GITHUB_DEMO_REPO=you/data-firefighter-demo`.

### 6. Trigger the demo incident

With both servers running, open the frontend and click **Column Deleted**.
Or via `curl`:

```bash
curl -X POST http://localhost:8000/api/incidents/demo
```

### 7. Run the tests

```bash
cd apps/api
uv run pytest        # 67 tests: unit, API, full-graph e2e, golden-file eval,
                      # RealDataHubClient (mocked GraphQL, no live instance needed)
```

## What's genuinely real vs. mocked

- **Real, always, regardless of `DATAHUB_MODE`:** GitHub branch/commit/PR
  creation against your configured repo. The LangGraph state machine and
  checkpointing. SQL fix generation (a deterministic AST transform via
  `sqlglot`, not LLM-freehand — a live demo depending on an LLM to
  hand-write correct SQL is a real hallucination risk this build
  deliberately avoids). Root-cause file attribution (cross-referenced
  against DataHub lineage AND a live GitHub code search — not either
  signal alone).
- **Real when `DATAHUB_MODE=real`:** `RealDataHubClient` makes actual
  GraphQL calls against a running DataHub GMS — entity metadata, lineage,
  and ownership all come back from DataHub itself, query shapes verified
  against DataHub's real GraphQL schema. Unit-tested against mocked GraphQL
  responses (`apps/api/tests/test_datahub_real.py`); not yet exercised
  against a live instance in this submission (see "Why DataHub").
- **Deterministic fixture data when `DATAHUB_MODE=mock`** (the recorded
  demo's setting): `MockDataHubClient` serves the same interface from
  `examples/incidents/customer_email_deletion/` fixtures. No silent
  fallback between the two modes — a `real`-mode failure surfaces as an
  explicit error, never a quiet switch to fixture data.
- **Deferred, not built:** Postgres persistence, the 3 non-primary
  incident types (column renamed/type changed/freshness breach — visibly
  disabled in the UI, not fake-wired), a full LLM eval framework, the
  replacement-column detection branch in `generate_fix`. Each is in
  `TODOS.md` with the reasoning for why it was cut and what picking it up
  would take.

## Future improvements

See `TODOS.md` — Postgres persistence, the other 3 incident types, and
replacement-column detection are the three highest-value next steps, each
already scoped with context for whoever picks them up.

## License

Apache 2.0 — see `LICENSE`.
