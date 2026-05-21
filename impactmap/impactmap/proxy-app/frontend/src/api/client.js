// api/client.js
// Single source of truth for all API calls.
// The ImpactMap analyzer parses this file to build the UI→API graph.

import axios from "axios";

const BASE = import.meta.env.VITE_API_URL || "http://localhost:8000";
const api = axios.create({ baseURL: BASE });

// ── Images ──────────────────────────────────────────────────
export const getImageUrl = (path) => `${BASE}${path}`;

// ── Products ─────────────────────────────────────────────────
export const fetchProducts = (params = {}) =>
  api.get("/products", { params });

export const fetchProduct = (productId) =>
  api.get(`/products/${productId}`);

// ── Cart ─────────────────────────────────────────────────────
export const fetchCart = () =>
  api.get("/cart");

export const addToCart = (productId, quantity = 1) =>
  api.post("/cart/add", { product_id: productId, quantity });

export const removeFromCart = (productId) =>
  api.delete(`/cart/item/${productId}`);

// ── Orders ───────────────────────────────────────────────────
export const placeOrder = (shippingAddr) =>
  api.post("/orders", { shipping_addr: shippingAddr });

export const fetchOrders = () =>
  api.get("/orders");

export const fetchOrder = (orderId) =>
  api.get(`/orders/${orderId}`);
