# ImpactMap — Project Specification

## Purpose

ImpactMap proves that you can automatically build a dependency graph by
statically parsing real application code, then use an LLM to trace any
natural language test scenario through that graph to answer:

- Which UI components does a tester need to exercise?
- Which API endpoints fire, and in what order?
- Which database tables are touched, and how (READ / WRITE)?
- What should a QA engineer verify, and what are the risks?

The LLM is grounded in the actual parsed graph — it is not guessing from
general knowledge. This is the core differentiator.

---

## Repository Layout

```
impactmap/
├── proxy-app/                  # Target app (the thing being analyzed)
│   ├── frontend/               # React + Vite
│   │   └── src/
│   │       ├── api/
│   │       │   └── client.js   # Single file: all API calls live here
│   │       ├── components/
│   │       │   ├── ProductList.jsx
│   │       │   ├── ProductCard.jsx
│   │       │   ├── Cart.jsx
│   │       │   ├── Checkout.jsx
│   │       │   └── Orders.jsx  # exports OrderConfirmation + OrderHistory
│   │       ├── App.jsx         # React Router setup
│   │       └── main.jsx
│   ├── backend/                # FastAPI + SQLAlchemy
│   │   ├── main.py             # All route handlers
│   │   ├── models.py           # SQLAlchemy ORM models (source of __tablename__)
│   │   ├── database.py         # Engine + SessionLocal + get_db() dependency
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── schema.sql              # Postgres DDL + seed data (still shipped for reference)
│   └── docker-compose.yml      # Postgres + backend + frontend
│
└── analyzer/                   # The ImpactMap CLI tool
    ├── parse_ui.py             # React source → component→API edges
    ├── parse_api.py            # FastAPI source → endpoint→table edges
    ├── introspect_db.py        # Live Postgres → table/column/FK graph
    ├── build_graph.py          # Orchestrates the three parsers → graph.json
    ├── analyze.py              # CLI entrypoint: graph + scenario → LLM → output
    └── requirements.txt        # anthropic, psycopg2-binary only
```

---

## Part 1: Proxy App

### Purpose
A deliberately simple e-commerce app. Domain chosen because it has clear
multi-table interactions (adding to cart touches `products` and `cart_items`;
placing an order touches four tables). Acts as the "real codebase" the
analyzer runs against.

### Frontend

**Stack:** React 18, Vite, React Router v6, Axios

**Key design decision:** All API calls are centralised in `src/api/client.js`.
This is intentional — the UI parser uses this file as its source of truth for
mapping function names to HTTP method + path. Components import named
functions from client.js; they do not call `fetch` or `axios` directly.

**client.js exports:**
```
fetchProducts    → GET  /products
fetchProduct     → GET  /products/:id
fetchCart        → GET  /cart
addToCart        → POST /cart/add
removeFromCart   → DELETE /cart/item/:id
placeOrder       → POST /orders
fetchOrders      → GET  /orders
fetchOrder       → GET  /orders/:id
```

**Components and their API calls:**
| Component | API calls made |
|---|---|
| ProductList | fetchProducts |
| ProductCard | addToCart |
| Cart | fetchCart, removeFromCart |
| Checkout | fetchCart, placeOrder |
| OrderConfirmation | fetchOrder |
| OrderHistory | fetchOrders |

**Routes (React Router):**
```
/                → ProductList
/cart            → Cart
/checkout        → Checkout
/orders          → OrderHistory
/orders/:orderId → OrderConfirmation
```

### Backend

**Stack:** FastAPI, SQLAlchemy 2.0, psycopg2-binary, Pydantic v2

**Key design decision:** Uses SQLAlchemy ORM (not raw SQL). This was
specifically chosen to match real-world patterns and to exercise the
ORM-aware parser. Models are in a separate `models.py` so the parser can
build a model-name → table-name registry before scanning routes.

**database.py:**
- Creates SQLAlchemy `engine` from `DATABASE_URL` env var
- `SessionLocal = sessionmaker(bind=engine)`
- `get_db()` — FastAPI dependency that yields a session and closes it

**models.py — SQLAlchemy models:**
| Class | `__tablename__` | Key relationships |
|---|---|---|
| User | users | has many CartItem, Order |
| Product | products | has many CartItem, OrderItem |
| CartItem | cart_items | FK → users.id, products.id |
| Order | orders | FK → users.id, has many OrderItem |
| OrderItem | order_items | FK → orders.id, products.id |

**main.py — API endpoints:**
| Method | Path | Models touched | Notes |
|---|---|---|---|
| GET | /products | Product (READ) | Filter by category, search |
| GET | /products/{id} | Product (READ) | |
| GET | /cart | CartItem (READ), Product (READ) | Joins product for details |
| POST | /cart/add | Product (READ), CartItem (WRITE) | Validates stock; upserts |
| DELETE | /cart/item/{id} | CartItem (WRITE) | |
| POST | /orders | CartItem (READ), Product (READ+WRITE), Order (WRITE), OrderItem (WRITE) | Full transaction: validate stock → create order → create line items → decrement stock → delete cart |
| GET | /orders | Order (READ) | |
| GET | /orders/{id} | Order (READ), OrderItem (READ), Product (READ) | |

**Demo user:** All requests use a hardcoded UUID
`00000000-0000-0000-0000-000000000001` (seeded in schema.sql). No auth layer.

### Database

**Postgres 16**

```sql
users        (id, email, name, created_at)
products     (id, name, description, price, stock_qty, category, created_at)
cart_items   (id, user_id→users, product_id→products, quantity, added_at)
             UNIQUE(user_id, product_id)
orders       (id, user_id→users, status, total_amount, shipping_addr, created_at)
order_items  (id, order_id→orders, product_id→products, quantity, unit_price)
```

Seed data: 1 demo user, 5 products across 5 categories.

### Running the proxy app

```bash
cd proxy-app
docker compose up --build
# Postgres → localhost:5432
# FastAPI  → http://localhost:8000
# React    → http://localhost:5173
```

Schema is applied automatically via Docker's
`/docker-entrypoint-initdb.d/schema.sql` mount on first run.

---

## Part 2: Analyzer

### Purpose
A Python CLI tool. Given paths to a UI repo, an API repo, and a live DB
connection string, it:
1. Parses the code to build a dependency graph (`graph.json`)
2. Accepts a natural language test scenario
3. Sends the graph + scenario to Claude
4. Prints a structured analysis to the terminal

### Dependencies
```
anthropic>=0.28.0
psycopg2-binary
```
That's it. No graph database, no heavy frameworks.

---

### parse_ui.py

**Input:** Path to a React source directory

**What it does:**
1. Finds `client.js` or `client.ts` anywhere under the directory
2. Regex-scans it for `export const fnName = ... api.METHOD('/path')` patterns
   → builds `{ "fetchCart": "GET /cart", "addToCart": "POST /cart/add", ... }`
3. Walks all `.jsx/.tsx/.js/.ts` files (skipping client.js, test files, vite config)
4. For each file: finds `import { fnName, ... } from '...client'` statements,
   checks which imported functions are actually called in the file body,
   maps them to their HTTP calls via the registry from step 2
5. Detects component name from function/arrow component declaration or filename

**Fallback:** Also regex-scans for raw `fetch(url)` and `axios.METHOD(url)` calls

**Output:**
```json
[
  {
    "component": "Cart",
    "file": "components/Cart.jsx",
    "api_calls": ["DELETE /cart/item/:param", "GET /cart"]
  }
]
```

---

### parse_api.py

**Input:** Path to a Python (FastAPI/Flask) or Node (Express) API directory

**Two-phase approach:**

**Phase 1 — Build model registry**
- Walks all `.py` files
- Finds `class ModelName(...)` declarations
- Within each class body, looks for `__tablename__ = "table_name"`
- Returns `{ "Product": "products", "CartItem": "cart_items", ... }`

**Phase 2 — Extract route → table mappings**
- Splits each `.py` file into per-route blocks by finding `@app.get/post/...` or
  `@router.get/post/...` decorator lines; each block runs from its decorator to
  the next decorator
- For each block, detects ORM operations:
  - `db.query(Model)` → READ on model's table
  - `db.add(Model(...))` → WRITE
  - `db.delete(instance)` → WRITE on the model that was queried in the same block
  - Attribute assignment `instance.field = value` → WRITE (inferred from model registry)
- Raw SQL fallback: `FROM table`, `INSERT INTO table`, `UPDATE table`, `DELETE FROM table`
- Validates all detected table names against `known_tables` (from DB introspection)
  to eliminate false positives

**Node/Express support:** Detects `router.get('/path', ...)` patterns + raw SQL strings

**Output:**
```json
[
  {
    "endpoint": "POST /orders",
    "file": "main.py",
    "tables": [
      {"name": "cart_items", "operations": ["READ", "WRITE"]},
      {"name": "order_items", "operations": ["WRITE"]},
      {"name": "orders",      "operations": ["WRITE"]},
      {"name": "products",    "operations": ["READ", "WRITE"]}
    ]
  }
]
```

---

### introspect_db.py

**Input:** A Postgres DSN string (e.g. `postgresql://user:pass@host:5432/db`)

**Replaces:** The original `parse_schema.py` which read a static `.sql` file.
Change was made to support real-world databases where you may not have a
schema file.

**Queries run:**
```sql
information_schema.tables              -- all user tables in schema
information_schema.columns             -- column names, data types, ordinal position
information_schema.table_constraints
  + key_column_usage                   -- which columns are primary keys
information_schema.referential_constraints
  + key_column_usage
  + constraint_column_usage            -- foreign key relationships
```

**Output** (same shape as the old parse_schema.py for drop-in compatibility):
```json
[
  {
    "table": "cart_items",
    "columns": [
      {"name": "id",         "type": "UUID",    "pk": true,  "fk": null},
      {"name": "user_id",    "type": "UUID",    "pk": false, "fk": "users.id"},
      {"name": "product_id", "type": "UUID",    "pk": false, "fk": "products.id"},
      {"name": "quantity",   "type": "INTEGER", "pk": false, "fk": null},
      {"name": "added_at",   "type": "TIMESTAMP WITHOUT TIME ZONE", "pk": false, "fk": null}
    ],
    "foreign_keys": [
      {"column": "user_id",    "references_table": "users",    "references_column": "id"},
      {"column": "product_id", "references_table": "products", "references_column": "id"}
    ]
  }
]
```

Also exports `get_table_names(dsn)` → `set[str]` used by `parse_api.py` for validation.

---

### build_graph.py

**Input:** UI dir path, API dir path, DB connection string

**Orchestrates** parse_ui → introspect_db → parse_api, then assembles edges:

**Component → Endpoint edges:**
- Exact match first: `"GET /cart"` in both UI and API → edge
- Fuzzy fallback: match by path only, ignoring method (handles cases where
  client.js uses `api.get('/cart/item/${id}')` and parser normalises to
  `GET /cart/item/:param`)

**Endpoint → Table edges:**
- Direct from parse_api output; one edge per (endpoint, table) pair,
  carrying the operations list

**Output — graph.json:**
```json
{
  "components": [
    {"id": "Cart", "file": "components/Cart.jsx", "api_calls": ["DELETE /cart/item/:param", "GET /cart"]}
  ],
  "endpoints": [
    {"id": "GET /cart", "file": "main.py", "tables": [{"name": "cart_items", "operations": ["READ"]}, ...]}
  ],
  "tables": [
    {"id": "cart_items", "columns": [...], "foreign_keys": [...]}
  ],
  "edges": {
    "component_to_endpoint": [{"from": "Cart", "to": "GET /cart"}],
    "endpoint_to_table":     [{"from": "GET /cart", "to": "cart_items", "operations": ["READ"]}]
  }
}
```

---

### analyze.py

**Main CLI entrypoint.**

**Two modes:**

1. **Build + analyze** (parses repos, saves graph.json, then analyzes):
```bash
python analyze.py \
  --ui     path/to/frontend/src \
  --api    path/to/backend \
  --db-url postgresql://user:pass@host:5432/dbname \
  --scenario "User adds item to cart and checks out"
```

2. **Analyze only** (uses pre-built graph.json, skips parsing):
```bash
python analyze.py \
  --graph graph.json \
  --scenario "User views order history"
```

3. **Interactive** (prompts for scenario):
```bash
python analyze.py --graph graph.json
```

**Additional flags:**
- `--save-graph PATH` — where to write graph.json (default: `./graph.json`)
- `--output PATH` — save analysis result JSON to file
- `--json` — print raw JSON instead of pretty terminal output

**LLM call:**
- Model: `claude-sonnet-4-20250514`
- Max tokens: 2000
- System prompt: serialised graph (all components, endpoints, tables, edges as
  plain text lists) + instructions to respond as a specific JSON schema
- User message: `"Test scenario: {scenario}"`
- API key from `ANTHROPIC_API_KEY` env var

**LLM output schema:**
```json
{
  "scenario_summary": "string",
  "ui_workflow": [
    {"step": 1, "component": "string", "action": "string", "triggers_apis": ["METHOD /path"]}
  ],
  "api_call_sequence": [
    {"order": 1, "endpoint": "METHOD /path", "triggered_by": "string",
     "purpose": "string", "table_operations": [{"table": "string", "operation": "READ|WRITE"}]}
  ],
  "impacted_tables": [
    {"table": "string", "operations": ["READ", "WRITE"],
     "reason": "string", "cascades_to": ["string"]}
  ],
  "test_checklist": ["string"],
  "risk_notes": "string"
}
```

**Terminal output sections** (colour-coded with ANSI):
1. SCENARIO — summary paragraph
2. UI WORKFLOW — table: step number, component name, action, API calls triggered
3. API CALL SEQUENCE — ordered list with table operations per call
4. IMPACTED TABLES — ASCII tree with READ/WRITE badges, column list from schema, cascade annotations
5. QA CHECKLIST — checkbox list
6. RISK NOTES — free text

---

## Design Decisions and Rationale

| Decision | Rationale |
|---|---|
| All API calls centralised in `client.js` | Makes the UI parser reliable; no need to find `fetch()` calls scattered across components |
| SQLAlchemy ORM instead of raw SQL | Matches real-world Python backends; exercises the two-phase model-registry parser |
| Live DB introspection instead of `.sql` file | Real projects often lack an up-to-date schema file; `information_schema` is always accurate |
| Static parsing (not runtime tracing) | Works without running the app; can be used in CI or on repos you can't execute |
| Graph serialised to plain text for LLM | More reliable than passing JSON; LLMs reason better over structured prose lists |
| LLM grounds in parsed graph | Prevents hallucination; the LLM cannot invent components or tables that don't exist in the graph |
| `known_tables` validation in parse_api | Filters out false positives (class names like `HTTPException` that match ORM patterns) |

---

## Known Limitations (PoC-grade)

- UI parser requires API calls to go through a single `client.js` file; scattered
  `fetch()` calls are detected by fallback regex but less reliably
- ORM parser uses regex, not AST; deeply nested or dynamically constructed queries
  may be missed
- No support for GraphQL, gRPC, or WebSocket endpoints
- No support for Django ORM (uses `.objects.filter()` pattern, not `db.query()`)
- No multi-schema Postgres support (assumes `public`)
- Component→endpoint edge matching is fuzzy for parameterised paths
  (e.g. `/orders/${id}` normalised to `/orders/:param` may not match `/orders/{order_id}`)
- One demo user hardcoded; no auth flow tested

---

## Environment Variables

| Variable | Used by | Description |
|---|---|---|
| `DATABASE_URL` | proxy-app backend, introspect_db.py | Postgres DSN |
| `VITE_API_URL` | proxy-app frontend | Backend base URL (default: http://localhost:8000) |
| `ANTHROPIC_API_KEY` | analyze.py | Claude API key |

---

## Setup Commands (reference)

```bash
# Proxy app
cd proxy-app && docker compose up --build

# Analyzer
cd analyzer
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...

# One-shot: build graph and analyze
python analyze.py \
  --ui     ../proxy-app/frontend/src \
  --api    ../proxy-app/backend \
  --db-url postgresql://postgres:postgres@localhost:5432/impactmap \
  --scenario "User searches for headphones, adds to cart, and places an order"

# Reuse graph
python analyze.py --graph graph.json \
  --scenario "User removes an item from their cart"
```
