CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE customers (
  id BIGSERIAL PRIMARY KEY,
  psid TEXT UNIQUE NOT NULL,          -- page-scoped ID tu Messenger
  name TEXT,
  phone TEXT,
  address TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE conversations (
  id BIGSERIAL PRIMARY KEY,
  customer_id BIGINT REFERENCES customers(id),
  bot_paused BOOLEAN NOT NULL DEFAULT FALSE,  -- human handoff
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE messages (
  id BIGSERIAL PRIMARY KEY,
  conversation_id BIGINT REFERENCES conversations(id),
  role TEXT NOT NULL CHECK (role IN ('customer', 'bot', 'agent')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE products (
  id BIGSERIAL PRIMARY KEY,
  sku TEXT UNIQUE NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  price_vnd INTEGER NOT NULL DEFAULT 0,
  stock INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE orders (
  id BIGSERIAL PRIMARY KEY,
  customer_id BIGINT REFERENCES customers(id),
  status TEXT NOT NULL DEFAULT 'new',  -- new | confirmed | shipped | done | cancelled
  total_vnd INTEGER NOT NULL DEFAULT 0,
  shipping_name TEXT,
  shipping_phone TEXT,
  shipping_address TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE order_items (
  id BIGSERIAL PRIMARY KEY,
  order_id BIGINT REFERENCES orders(id),
  product_id BIGINT REFERENCES products(id),
  quantity INTEGER NOT NULL,
  unit_price_vnd INTEGER NOT NULL
);

-- Knowledge base cho RAG (dimension 1536 = text-embedding-3-small)
CREATE TABLE knowledge_chunks (
  id BIGSERIAL PRIMARY KEY,
  source TEXT NOT NULL,
  content TEXT NOT NULL,
  embedding vector(1536),
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX knowledge_chunks_embedding_idx
  ON knowledge_chunks USING hnsw (embedding vector_cosine_ops);

-- Bang gia theo so luong (bac gia si). Don >100 hu: KHONG ap gia tu dong, escalate cho staff.
CREATE TABLE price_tiers (
  id BIGSERIAL PRIMARY KEY,
  product_id BIGINT REFERENCES products(id),
  min_qty INTEGER NOT NULL,
  unit_price_vnd INTEGER NOT NULL,
  UNIQUE (product_id, min_qty)
);

-- Seed san pham chinh (price_vnd = gia le 1-4 hu)
INSERT INTO products (sku, name, description, price_vnd, stock) VALUES (
  '3S-100G',
  '3S Coffee – Hũ 100g',
  'Cà phê sấy lạnh nguyên chất, 100% Robusta (phôi Ro-Express R100). Hòa tan 3 giây với nước nguội/đá. ~50 ly/hũ (2g/ly).',
  170000,
  0
);

-- Bac gia 3S-100G: 1-4 hu 170k | 5-19 hu 160k | 20-100 hu 140k | >100 hu: chuyen staff
INSERT INTO price_tiers (product_id, min_qty, unit_price_vnd)
SELECT id, t.min_qty, t.unit_price_vnd
FROM products, (VALUES (1, 170000), (5, 160000), (20, 140000)) AS t(min_qty, unit_price_vnd)
WHERE sku = '3S-100G';
