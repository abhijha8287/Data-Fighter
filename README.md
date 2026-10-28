# Data Firefighter

An agent that investigates a data incident (for example, a deleted column), traces what it breaks through DataHub lineage, and opens a fix PR after a human approves.

## Why this exists
Built for the DataHub "Build with DataHub: The Agent Hackathon". A schema change on one dataset can silently break every pipeline, dashboard and model downstream, and finding out what broke is usually a manual, multi-tool search. This automates the investigation using DataHub as the source of lineage, schema and ownership.

## What it does
- Runs an 11-step LangGraph workflow: detect incident → fetch context → trace lineage → blast radius → owners → root cause → generate fix → validate fix → create PR → incident report → write back to DataHub
- Pauses for explicit human approval before it touches GitHub (it is not fully autonomous)
- Keeps agent state in a SQLite checkpoint so the run can resume after approval
- Works against mock DataHub fixtures by default, or a real DataHub instance
- Shows the investigation and approval step in a Next.js dashboard

## Project structure
```
Data-Fighter/
├── apps/
│   ├── api/
│   │   ├── app/agents/     LangGraph nodes and graph
│   │   ├── app/api/        FastAPI routes
│   │   ├── app/datahub/    DataHub client (mock and real)
│   │   ├── app/github/     Code search and PR creation
│   │   ├── app/incidents/  Incident models and storage
│   │   └── tests/          Unit and eval tests
│   └── web/                Next.js dashboard
├── examples/incidents/     Demo incident fixture files
├── scripts/                DataHub seeding script
├── TODOS.md                Open work items
└── .env.example            Required settings
```

## Getting started
Requirements: Python 3.12+ with `uv`, Node.js 18+, a GitHub token and a throwaway repo seeded with `examples/incidents/customer_email_deletion`.
```bash
git clone https://github.com/abhijha8287/Data-Fighter.git
cd Data-Fighter
cp .env.example apps/api/.env          # fill in the values below

cd apps/api
uv sync
uv run uvicorn app.main:app --reload --port 8000

cd ../web                              # in a second terminal
npm install
npm run dev
```

## Configuration
| Variable | Purpose |
|:--|:--|
| `LLM_PROVIDER` | `openai` or `anthropic` |
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` | Key for the chosen provider |
| `DATAHUB_MODE` | `mock` (default) or `real` |
| `DATAHUB_GMS_URL`, `DATAHUB_GMS_TOKEN` | Only for `DATAHUB_MODE=real` |
| `DATAHUB_MUTATION_ENABLED` | Allows writing results back to DataHub |
| `GITHUB_TOKEN` | Needed in every mode: the agent searches and opens PRs |
| `GITHUB_DEMO_REPO` | `owner/repo` the agent works on |
| `CHECKPOINT_DB_PATH` | SQLite file for agent checkpoints |
| `FRONTEND_ORIGINS` | Allowed frontend URLs (comma-separated) |

## Tech stack
Python, LangGraph, LangChain (OpenAI / Anthropic), FastAPI, DataHub, PyGithub, SQLite, Next.js, TypeScript, Tailwind CSS

## Notes
Demo data lives in [data-firefighter-demo](https://github.com/abhijha8287/data-firefighter-demo). MIT licensed.

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

## Setup details

### 1. Backend

```bash
cd apps/api
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd apps/web
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
