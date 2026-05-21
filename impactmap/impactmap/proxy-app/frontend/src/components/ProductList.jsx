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
  const categoryLabels = {
    "": "All Categories",
    electronics: "Electronics",
    footwear: "Footwear",
    kitchen: "Kitchen",
    fitness: "Fitness",
    home: "Home",
  };

  return (
    <div className="product-list">
      <div className="search-bar">
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          {categories.map((c) => (
            <option key={c} value={c}>{categoryLabels[c]}</option>
          ))}
        </select>
        <input
          type="text"
          placeholder="Search products..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="button">Search</button>
      </div>
      {loading ? (
        <p className="loading">Loading products...</p>
      ) : (
        <div className="product-grid">
          {products.map((p) => <ProductCard key={p.id} product={p} />)}
        </div>
      )}
    </div>
  );
}
