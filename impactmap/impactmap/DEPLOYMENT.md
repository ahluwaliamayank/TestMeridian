# ImpactMap

Prove that you can parse a UI repo + API repo + DB schema, build a dependency
graph, and — given a plain-English test scenario — have an LLM tell you:
- Which UI components to exercise (and in what order)
- Which API endpoints fire
- Which database tables get touched (READ / WRITE) and why

---

## What's in here

```
impactmap/
├── proxy-app/               ← The "target" app you point the tool at
│   ├── frontend/            ← React (Vite) e-commerce UI
│   ├── backend/             ← FastAPI + raw psycopg2
│   ├── schema.sql           ← Postgres schema (5 tables)
│   └── docker-compose.yml
│
└── analyzer/                ← The ImpactMap CLI tool
    ├── parse_ui.py          ← Walks React source, extracts component → API edges
    ├── parse_api.py         ← Walks FastAPI source, extracts endpoint → table edges
    ├── parse_schema.py      ← Parses .sql or .prisma, extracts tables + FK graph
    ├── build_graph.py       ← Assembles graph.json
    ├── analyze.py           ← Main CLI: takes scenario, calls Claude, prints result
    └── requirements.txt
```

---

## 1 · Deploy the proxy app

### Prerequisites
- Docker + Docker Compose
- Node 20+ (if running frontend without Docker)
- Python 3.11+ (if running backend without Docker)

### With Docker (recommended)

```bash
cd impactmap/proxy-app
docker compose up --build
```

This starts:
| Service  | URL                   |
|----------|-----------------------|
| Postgres | localhost:5432        |
| FastAPI  | http://localhost:8000 |
| React    | http://localhost:5173 |

The schema is applied automatically on first run (mounted into
`/docker-entrypoint-initdb.d/`). Seed data (5 products, 1 demo user) is
included in schema.sql.

### Without Docker

**Postgres**
```bash
createdb impactmap
psql impactmap < schema.sql
```

**Backend**
```bash
cd proxy-app/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=postgresql://localhost/impactmap uvicorn main:app --reload
```

**Frontend**
```bash
cd proxy-app/frontend
npm install
VITE_API_URL=http://localhost:8000 npm run dev
```

Open http://localhost:5173 — you'll see a working shop: browse products,
add to cart, check out, view order history.

---

## 2 · Run the ImpactMap analyzer

### Prerequisites

```bash
cd impactmap/analyzer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
```

### Option A — Build graph + analyze in one command

```bash
python analyze.py \
  --ui     ../proxy-app/frontend/src \
  --api    ../proxy-app/backend \
  --schema ../proxy-app/schema.sql \
  --scenario "User searches for headphones, adds them to the cart, and completes checkout"
```

This will:
1. Parse the React source → component→API edges
2. Parse the FastAPI source → endpoint→table edges
3. Parse schema.sql → table graph with FK relationships
4. Write `graph.json` to the current directory
5. Send the graph + scenario to Claude
6. Print a pretty terminal analysis

### Option B — Build graph once, reuse it

```bash
# Build
python build_graph.py \
  ../proxy-app/frontend/src \
  ../proxy-app/backend \
  ../proxy-app/schema.sql \
  graph.json

# Analyze (fast, no re-parsing)
python analyze.py --graph graph.json \
  --scenario "User removes an item from the cart"

python analyze.py --graph graph.json \
  --scenario "User checks their order history"
```

### Option C — Interactive mode

```bash
python analyze.py --graph graph.json
# Prompts: "Enter test scenario: "
```

### Flags

| Flag | Description |
|------|-------------|
| `--ui PATH` | React source directory |
| `--api PATH` | FastAPI / backend source directory |
| `--schema PATH` | schema.sql or schema.prisma |
| `--graph PATH` | Pre-built graph.json (skips parsing) |
| `--scenario TEXT` | Test scenario in natural language |
| `--save-graph PATH` | Where to write graph.json (default: ./graph.json) |
| `--output PATH` | Save analysis JSON to file |
| `--json` | Print raw JSON instead of pretty output |

---

## 3 · Sample output

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  IMPACTMAP ANALYSIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCENARIO
  User searches for headphones, adds them to the cart, and checks out.

UI WORKFLOW
  Step  Component                 Action
  ───────────────────────────────────────────────────────────────────────
  1     ProductList               User types "headphones" in search input
          ↳ GET /products
  2     ProductCard               User clicks "Add to Cart"
          ↳ POST /cart/add
  3     Cart                      User reviews cart, clicks Proceed to Checkout
          ↳ GET /cart
  4     Checkout                  User enters address, clicks Place Order
          ↳ GET /cart
          ↳ POST /orders

API CALL SEQUENCE
  1.  GET /products
      ← ProductList
      Fetch filtered product list matching "headphones"
        ├─ READ         products

  2.  POST /cart/add
      ← ProductCard
      Add selected product to cart
        ├─ READ         products
        ├─ WRITE        cart_items

  3.  GET /cart
      ← Cart / Checkout
      Load cart contents with line totals
        ├─ READ         cart_items
        ├─ READ         products

  4.  POST /orders
      ← Checkout
      Place the order, decrement stock, clear cart
        ├─ READ         cart_items
        ├─ WRITE        orders
        ├─ WRITE        order_items
        ├─ WRITE        products
        ├─ WRITE        cart_items

IMPACTED TABLES
  ├─ products   READ WRITE
  │     Queried for search results and prices; stock_qty decremented on order
  │     cols: id, name, description, price, stock_qty, category, created_at
  ├─ cart_items READ WRITE
  │     Written when item added; read at checkout; deleted after order placed
  │     cols: id, user_id, product_id, quantity, added_at
  ├─ orders     WRITE
  │     New order row created on POST /orders
  │     cols: id, user_id, status, total_amount, shipping_addr, created_at
  └─ order_items WRITE
        One row per cart item written to preserve the order snapshot
        cols: id, order_id, product_id, quantity, unit_price

QA CHECKLIST
  □ Verify search returns correct products when filtering by name
  □ Verify cart_items quantity increments correctly on duplicate add
  □ Verify stock_qty decrements by the correct amount after order
  □ Verify cart_items rows are deleted after order is placed
  □ Verify order total matches sum of (price × quantity) for all items
  □ Verify order status is set to "confirmed" immediately

⚠  RISK NOTES
  POST /orders is not atomic by default with raw SQL — if the server crashes
  after writing orders but before decrementing stock, inventory will be
  over-counted. Consider wrapping in a transaction. Also: no payment step
  means orders are placed without charge validation.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

---

## 4 · Pointing at a real repo

The parsers are generic. To use on your own codebase:

```bash
python analyze.py \
  --ui     /path/to/your/react/src \
  --api    /path/to/your/fastapi/or/express/routes \
  --schema /path/to/your/schema.sql \
  --scenario "Your scenario here"
```

**React**: Works with `.jsx`, `.tsx`, `.js`, `.ts`. Detects imports from any
file named `client.js/ts`, plus raw `fetch()`/`axios.*()` calls.

**API**: Detects `@app.get`, `@router.post`, etc. (FastAPI/Flask) and
`router.get()` (Express). Extracts table names from SQL strings and ORM
patterns. Pass `--schema` so the parser validates table names against the
real schema.

**Schema**: Supports `.sql` (CREATE TABLE statements) and `.prisma` files.
