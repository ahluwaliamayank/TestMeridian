# ImpactMap

Two things in one repo:

1. **`proxy-app/`** — A simple e-commerce app (React + FastAPI + Postgres) that acts as the target system to analyze.
2. **`analyzer/`** — A Python CLI tool that parses the proxy-app's UI code, API code, and DB schema to build a dependency graph, then accepts a natural language scenario and returns the UI workflow + impacted tables.

## Structure

```
impactmap/
├── proxy-app/
│   ├── frontend/        # React app (Vite)
│   ├── backend/         # FastAPI app
│   ├── docker-compose.yml
│   └── .env.example
└── analyzer/
    ├── parse_ui.py       # Parses React components for API calls
    ├── parse_api.py      # Parses FastAPI routes for ORM/table usage
    ├── parse_schema.py   # Parses SQL schema for tables + FK relations
    ├── build_graph.py    # Assembles graph.json
    ├── analyze.py        # LLM scenario analyzer (main CLI entrypoint)
    └── requirements.txt
```
