# TestMeridian — ImpactMap

TestMeridian is an intelligent test impact analysis tool. It statically parses a real application's UI code, API code, and database schema, builds a dependency graph, and uses Claude LLM to generate targeted test scenarios, trace impact paths, and assess risk from code changes.

## What It Does

Given a plain-English test scenario, TestMeridian tells you:

- **Which UI components** to exercise and in what order
- **Which API endpoints** fire and their sequence
- **Which database tables** get touched (READ/WRITE) and why
- **Suggested test cases** with data requirements and risk notes

## Project Structure

```
impactmap/
├── docker-compose.yml         # Orchestrates all services
├── resources/                 # Product images + logo
├── proxy-app/                 # Sample e-commerce app (analysis target)
│   ├── frontend/              # React (Vite) SPA
│   ├── backend/               # FastAPI + SQLAlchemy ORM
│   └── schema.sql             # Postgres DDL + seed data
└── analyzer/                  # TestMeridian analysis tool
    ├── analyze.py             # CLI: scenario analysis, reverse trace, diff impact
    ├── dashboard.py           # Streamlit web dashboard
    ├── build_graph.py         # Assembles dependency graph
    ├── parse_ui.py            # React/JSX parser (tree-sitter)
    ├── parse_api.py           # FastAPI parser (tree-sitter + ast)
    ├── introspect_db.py       # Live Postgres introspection
    ├── diff_impact.py         # Git diff → blast radius analysis
    ├── syngen_client.py       # HTTP client for syngen-api
    └── syngen_workflow.py     # Synthetic data generation workflow
```

## Quick Start

```bash
export ANTHROPIC_API_KEY=sk-ant-...
cd impactmap/impactmap
docker compose up --build
```

| Service   | URL                   |
|-----------|-----------------------|
| Frontend  | http://localhost:5173 |
| Backend   | http://localhost:8000 |
| Analyzer  | http://localhost:8501 |
| Database  | localhost:5435        |

## Analysis Modes

- **Scenario Analysis** — Describe a user flow, get the full impact trace
- **System Overview** — Auto-generate feature areas and test cases for the entire system
- **Reverse Trace** — Pick a component, endpoint, or table and find all scenarios that touch it
- **Diff Impact** — Point at a git ref, get risk-ranked test scenarios for your changes

## Synthetic Data Generation (Optional)

TestMeridian can integrate with [syngen-api](syngen/syngen-api/) to automatically generate synthetic test data for tables identified during scenario analysis. When enabled, a "Generate Data" button appears in the test data setup section.

To enable, export these additional variables before starting:

```bash
export LINK_SYNTHETIC_DATA=true
export SYNGEN_API_URL=https://host.docker.internal
export DCT_API_KEY=<your-syngen-api-key>
export SYNGEN_JDBC_DRIVER_ID=<uploaded-jdbc-driver-file-id>
```

See [DEPLOYMENT.md](impactmap/impactmap/DEPLOYMENT.md) for details.

## Deployment

For detailed setup, cleanup, and troubleshooting instructions, see [DEPLOYMENT.md](DEPLOYMENT.md).

## Tech Stack

- **Analyzer:** Python, tree-sitter, Anthropic Claude API, Streamlit
- **Backend:** FastAPI, SQLAlchemy, PostgreSQL
- **Frontend:** React, React Router, Axios, Vite
- **Infrastructure:** Docker Compose
