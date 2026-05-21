# ImpactMap — Deployment Guide

Statically parses a UI repo + API repo + DB schema, builds a dependency
graph, and — given a plain-English test scenario — uses an LLM to tell you:
- Which UI components to exercise (and in what order)
- Which API endpoints fire
- Which database tables get touched (READ / WRITE) and why

---

## Project Structure

```
impactmap/
├── docker-compose.yml        ← Orchestrates all services
├── resources/                ← Product images served by the backend
│   ├── headphones.jpg
│   ├── running-shoes.jpg
│   ├── coffee-grinder.jpg
│   ├── yoga-mat.jpg
│   └── desklamp.jpg
│
├── proxy-app/                ← The "target" e-commerce app
│   ├── frontend/             ← React (Vite) SPA
│   ├── backend/              ← FastAPI + SQLAlchemy ORM
│   └── schema.sql            ← Postgres DDL + seed data (5 tables)
│
└── analyzer/                 ← The ImpactMap analysis tool
    ├── analyze.py            ← CLI: scenario analysis, reverse trace, diff impact
    ├── dashboard.py          ← Streamlit web dashboard
    ├── parse_ui.py           ← React/JSX parser (tree-sitter)
    ├── parse_api.py          ← FastAPI parser (tree-sitter + ast)
    ├── introspect_db.py      ← Live Postgres introspection
    ├── build_graph.py        ← Assembles graph.json
    ├── diff_impact.py        ← Git diff → blast radius analysis
    ├── syngen_client.py      ← HTTP client for syngen-api
    ├── syngen_workflow.py    ← Synthetic data generation workflow
    └── requirements.txt
```

---

## Prerequisites

- **Docker** and **Docker Compose**
- An **Anthropic API key** (for the analyzer)
- (Optional) A running **syngen-api** instance + API key for synthetic data generation

Everything runs in containers.

---

## 1 · Environment Setup

### Create your `.env` file

```bash
cp .env.example .env
```

Edit `.env` and add your Anthropic API key:

```
ANTHROPIC_API_KEY=sk-ant-...
```

### Export the API key

Docker Compose reads environment variables from your shell:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

### (Optional) Synthetic data generation

To enable the syngen-api integration for generating synthetic test data:

```bash
export LINK_SYNTHETIC_DATA=true
export SYNGEN_API_URL=https://host.docker.internal
export DCT_API_KEY=<your-syngen-api-key>
export SYNGEN_JDBC_DRIVER_ID=<uploaded-jdbc-driver-file-id>
```

| Variable | Required | Description |
|----------|----------|-------------|
| `LINK_SYNTHETIC_DATA` | No | Set to `true` to enable. Default: `false` |
| `SYNGEN_API_URL` | If enabled | Base URL of the syngen-api instance (use `https://host.docker.internal` when running in Docker) |
| `DCT_API_KEY` | If enabled | API key for syngen-api authentication |
| `SYNGEN_JDBC_DRIVER_ID` | If enabled | File upload ID of a pre-uploaded PostgreSQL JDBC driver in syngen-api |

**Prerequisites for syngen integration:**
1. A running syngen-api instance accessible from the analyzer container
2. A PostgreSQL JDBC driver JAR uploaded to syngen-api via `POST /dct/v3/synthetic/file-uploads`
3. The file upload ID from step 2 set as `SYNGEN_JDBC_DRIVER_ID`

---

## 2 · Start All Services

From the `impactmap/impactmap/` directory:

```bash
docker compose up --build
```

This starts four services:

| Service    | URL                     | Description                          |
|------------|-------------------------|--------------------------------------|
| db         | localhost:5435          | PostgreSQL 16 with schema + seed data|
| backend    | http://localhost:8000   | FastAPI REST API + static images     |
| frontend   | http://localhost:5173   | React e-commerce storefront          |
| analyzer   | http://localhost:8501   | Streamlit analysis dashboard         |

You can connect to the database directly using any Postgres client:

```bash
psql -h localhost -p 5435 -U postgres -d impactmap
# Password: postgres
```

The database schema and seed data (5 products, 1 demo user) are applied automatically on first startup via `schema.sql`.

Product images from `resources/` are served by the backend at `/images/` (e.g., `http://localhost:8000/images/headphones.jpg`).

---

## 3 · Cleaning Up a Previous Setup

If you have previously set up this application (e.g., standalone Postgres containers, old volumes, or a prior docker-compose deployment), follow these steps before starting fresh.

### Stop and remove old containers

```bash
# Stop any standalone Postgres containers from earlier setup
docker stop db-testmeridian 2>/dev/null
docker rm db-testmeridian 2>/dev/null

# Stop any previous compose deployment
cd impactmap/impactmap
docker compose down
```

### Remove old database volumes

The database volume must be removed if the schema has changed (e.g., new columns, updated seed data). Postgres only runs `schema.sql` on **first initialization** — if the volume already exists, schema changes are ignored.

```bash
docker compose down -v
```

> **Warning:** `-v` deletes all data in the database. Only use this when you need a fresh schema.

### Remove old Docker images (optional)

If you want to force a full rebuild (e.g., after changing `requirements.txt` or `Dockerfile`):

```bash
docker compose down -v --rmi local
```

### Start fresh

```bash
docker compose up --build
```

---

## 4 · Using the Analyzer

### Via Streamlit Dashboard (recommended)

Open http://localhost:8501 in your browser. The dashboard provides an interactive interface for:
- Scenario analysis
- System-wide test generation
- Reverse tracing (component/endpoint/table → scenarios)
- Git diff impact analysis

### Via CLI (inside the analyzer container)

```bash
docker compose exec analyzer python analyze.py \
  --ui /proxy-app/frontend/src \
  --api /proxy-app/backend \
  --db-url postgresql://postgres:postgres@db:5432/impactmap \
  --scenario "User searches for headphones, adds them to the cart, and completes checkout"
```

### CLI with a pre-built graph

```bash
# Build the graph once
docker compose exec analyzer python analyze.py \
  --ui /proxy-app/frontend/src \
  --api /proxy-app/backend \
  --db-url postgresql://postgres:postgres@db:5432/impactmap \
  --save-graph graph.json

# Analyze scenarios without re-parsing
docker compose exec analyzer python analyze.py \
  --graph graph.json \
  --scenario "User removes an item from the cart"
```

### CLI Flags

| Flag             | Description                                    |
|------------------|------------------------------------------------|
| `--ui PATH`      | React source directory                         |
| `--api PATH`     | FastAPI / backend source directory              |
| `--db-url URL`   | PostgreSQL connection string (live introspection)|
| `--graph PATH`   | Pre-built graph.json (skips parsing)            |
| `--scenario TEXT` | Test scenario in natural language               |
| `--save-graph PATH` | Where to write graph.json (default: ./graph.json) |
| `--output PATH`  | Save analysis JSON to file                      |
| `--json`         | Print raw JSON instead of pretty output         |

---

## 5 · Synthetic Data Generation

When `LINK_SYNTHETIC_DATA=true`, a "Generate Data" button appears in the scenario analysis results whenever the test data setup indicates pre-existing data is required.

Clicking this button opens a slide-out conversational panel that automatically:

1. Creates or finds the "Amazone" application in syngen-api
2. Registers the PostgreSQL JDBC driver (if not already registered)
3. Creates a database connector pointing to the proxy-app database (`localhost:5435`)
4. Triggers schema discovery (ASDD)
5. Creates a dataset with the required tables
6. Generates 1 record of synthetic data per table

The connector uses the EXTENDED subtype with a pre-uploaded PostgreSQL JDBC driver. The same connector serves as both reference (for schema discovery) and target (for data generation).

**Note:** The syngen-api instance must be able to reach the proxy-app database at `localhost:5435`. If syngen-api runs in Docker, you may need `host.docker.internal` instead.

---

## 6 · Running Without Docker

If you prefer to run services locally without Docker, you'll need:
- **Python 3.11+**
- **Node 20+**
- **PostgreSQL 16**

### Database

```bash
createdb impactmap
psql impactmap < proxy-app/schema.sql
```

### Backend

```bash
cd proxy-app/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
# Create an /images directory or symlink to resources/
ln -s ../../resources /images
DATABASE_URL=postgresql://localhost/impactmap uvicorn main:app --reload
```

### Frontend

```bash
cd proxy-app/frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

### Analyzer

```bash
cd analyzer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# Streamlit dashboard
streamlit run dashboard.py

# Or CLI
python analyze.py \
  --ui ../proxy-app/frontend/src \
  --api ../proxy-app/backend \
  --db-url postgresql://localhost/impactmap \
  --scenario "Your scenario here"
```

---

## 7 · Troubleshooting

### Database schema not applied

Postgres only runs init scripts on first startup. If you changed `schema.sql`, remove the volume:

```bash
docker compose down -v
docker compose up --build
```

### Port conflicts

The proxy-app database is exposed on port `5435` to avoid conflicts with other Postgres instances (e.g., syngen-api on `5432`). If port `5435` is in use, stop the conflicting service:

```bash
# Find what's using the port
lsof -i :5435

# Stop it (example: standalone container)
docker stop <container-name>
```

### Backend can't connect to database

The backend connects to `db:5432` via Docker's internal network. If you see connection errors:
1. Ensure the `db` service is running: `docker compose ps`
2. Check logs: `docker compose logs db`
3. The database may still be initializing — wait a few seconds and retry

### Images not loading

Ensure the `resources/` directory exists and contains the product images. The backend serves them from `/images/` via the volume mount `./resources:/images`.

### Analyzer API key errors

Ensure `ANTHROPIC_API_KEY` is exported in your shell before running `docker compose up`:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up
```
