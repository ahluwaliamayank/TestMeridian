-- ImpactMap Proxy App Schema
-- E-commerce domain: products, cart, orders

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── products ─────────────────────────────────────────────────
CREATE TABLE products (
    id          VARCHAR(300) PRIMARY KEY DEFAULT uuid_generate_v4(),
    name        VARCHAR(200)   NOT NULL,
    description TEXT,
    price       DECIMAL(10,2)  NOT NULL,
    stock_qty   INT            NOT NULL DEFAULT 0,
    category    VARCHAR(100),
    image_url   VARCHAR(500),
    created_at  TIMESTAMP      DEFAULT NOW()
);

-- ── users ────────────────────────────────────────────────────
CREATE TABLE users (
    id          VARCHAR(300) PRIMARY KEY DEFAULT uuid_generate_v4(),
    email       VARCHAR(200)   NOT NULL UNIQUE,
    name        VARCHAR(200)   NOT NULL,
    created_at  TIMESTAMP      DEFAULT NOW()
);

-- ── cart_items ───────────────────────────────────────────────
CREATE TABLE cart_items (
    id          VARCHAR(300) PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     VARCHAR(300)           NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id  VARCHAR(300)           NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity    INT            NOT NULL DEFAULT 1,
    added_at    TIMESTAMP      DEFAULT NOW(),
    UNIQUE(user_id, product_id)
);

-- ── orders ───────────────────────────────────────────────────
CREATE TABLE orders (
    id            VARCHAR(300) PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id       VARCHAR(300)           NOT NULL REFERENCES users(id),
    status        VARCHAR(50)    NOT NULL DEFAULT 'pending',
    total_amount  DECIMAL(10,2)  NOT NULL,
    shipping_addr TEXT,
    created_at    TIMESTAMP      DEFAULT NOW()
);

-- ── order_items ──────────────────────────────────────────────
CREATE TABLE order_items (
    id          VARCHAR(300) PRIMARY KEY DEFAULT uuid_generate_v4(),
    order_id    VARCHAR(300)           NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  VARCHAR(300)           NOT NULL,
    quantity    INT            NOT NULL,
    unit_price  DECIMAL(10,2)  NOT NULL
);

-- ── seed data ────────────────────────────────────────────────
INSERT INTO users (id, email, name) VALUES
    ('00000000-0000-0000-0000-000000000001', 'demo@example.com', 'Demo User');

INSERT INTO products (id, name, description, price, stock_qty, category, image_url) VALUES
    ('153fcb29-eebe-44e8-8185-b3df2da98c78', 'Wireless Headphones', 'Noise-cancelling over-ear headphones', 149.99, 50, 'electronics', '/images/headphones.jpg'),
    ('eb0dcd6e-8981-472c-9eb0-4aacf27276e8', 'Running Shoes', 'Lightweight trail runners, size 10', 89.99, 30, 'footwear', '/images/running-shoes.jpg'),
    ('428035d5-308f-4925-aa48-213501b1837c', 'Coffee Grinder', 'Burr grinder, 15 grind settings', 59.99, 20, 'kitchen', '/images/coffee-grinder.jpg'),
    ('478da581-d989-4501-9b0e-2f5dd565dce5', 'Yoga Mat', 'Non-slip 6mm thick mat', 34.99, 100, 'fitness', '/images/yoga-mat.jpg'),
    ('aece1651-faad-438f-8e2d-9fb27676fcd6', 'Desk Lamp', 'LED with adjustable colour temperature', 44.99, 45, 'home', '/images/desklamp.jpg');
