// components/ProductList.jsx
// Displays all products. Supports search and category filter.
// API calls: fetchProducts (GET /products)

import { useEffect, useState } from "react";
import { fetchProducts } from "../api/client";
import ProductCard from "./ProductCard";

export default function ProductList() {
  const [products, setProducts] = useState([]);
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    fetchProducts({ search: search || undefined, category: category || undefined })
      .then((r) => setProducts(r.data))
      .finally(() => setLoading(false));
  }, [search, category]);

  const categories = ["", "electronics", "footwear", "kitchen", "fitness", "home"];

  return (
    <div className="product-list">
      <div className="filters">
        <input
          placeholder="Search products..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {categories.map((c) => (
            <option key={c} value={c}>{c || "All categories"}</option>
          ))}
        </select>
      </div>
      {loading ? (
        <p>Loading...</p>
      ) : (
        <div className="product-grid">
          {products.map((p) => <ProductCard key={p.id} product={p} />)}
        </div>
      )}
    </div>
  );
}
