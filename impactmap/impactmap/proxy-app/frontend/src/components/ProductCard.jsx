// components/ProductCard.jsx
// Renders a single product. Add to Cart button.
// API calls: addToCart (POST /cart/add)

import { useState } from "react";
import { addToCart } from "../api/client";

export default function ProductCard({ product }) {
  const [adding, setAdding] = useState(false);
  const [added, setAdded] = useState(false);

  const handleAddToCart = async () => {
    setAdding(true);
    try {
      await addToCart(product.id, 1);
      setAdded(true);
      setTimeout(() => setAdded(false), 2000);
    } catch (e) {
      alert(e.response?.data?.detail || "Could not add to cart");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="product-card">
      <div className="product-category">{product.category}</div>
      <h3>{product.name}</h3>
      <p>{product.description}</p>
      <div className="product-footer">
        <span className="price">${product.price}</span>
        <span className="stock">{product.stock_qty} in stock</span>
        <button onClick={handleAddToCart} disabled={adding || product.stock_qty === 0}>
          {adding ? "Adding..." : added ? "Added ✓" : "Add to Cart"}
        </button>
      </div>
    </div>
  );
}
