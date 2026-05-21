// components/ProductCard.jsx
// Renders a single product. Add to Cart button.
// API calls: addToCart (POST /cart/add)

import { useState } from "react";
import { addToCart, getImageUrl } from "../api/client";

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

  const inStock = product.stock_qty > 0;

  return (
    <div className="product-card">
      <div className="product-card-image">
        {product.image_url ? (
          <img src={getImageUrl(product.image_url)} alt={product.name} />
        ) : (
          <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
          </svg>
        )}
      </div>
      <span className="product-card-category">{product.category}</span>
      <h3>{product.name}</h3>
      <p className="product-card-description">{product.description}</p>
      <div className="product-card-price">${product.price}</div>
      <div className={`product-card-stock ${inStock ? "in-stock" : "out-of-stock"}`}>
        {inStock ? `In Stock (${product.stock_qty})` : "Out of Stock"}
      </div>
      <button
        className={`btn-add-to-cart${added ? " added" : ""}`}
        onClick={handleAddToCart}
        disabled={adding || !inStock}
      >
        {adding ? "Adding..." : added ? "Added ✓" : "Add to Cart"}
      </button>
    </div>
  );
}
