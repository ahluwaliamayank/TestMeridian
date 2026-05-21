// components/Cart.jsx
// Shows current cart contents. Remove items. Link to Checkout.
// API calls: fetchCart (GET /cart), removeFromCart (DELETE /cart/item/:id)

import { useEffect, useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { fetchCart, removeFromCart } from "../api/client";

export default function Cart() {
  const [cart, setCart] = useState({ items: [], total: 0 });
  const [loading, setLoading] = useState(true);
  const navigate = useNavigate();

  const loadCart = () => {
    setLoading(true);
    fetchCart()
      .then((r) => setCart(r.data))
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadCart(); }, []);

  const handleRemove = async (productId) => {
    await removeFromCart(productId);
    loadCart();
  };

  if (loading) return <p className="loading">Loading cart...</p>;

  if (cart.items.length === 0) {
    return (
      <div className="cart-empty">
        <p>Your cart is empty.</p>
        <Link to="/">Continue shopping</Link>
      </div>
    );
  }

  return (
    <div className="cart-page">
      <div className="cart-items">
        <h2>Shopping Cart</h2>
        {cart.items.map((item) => (
          <div key={item.product_id} className="cart-item">
            <div className="cart-item-image">
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.25 15.75l5.159-5.159a2.25 2.25 0 013.182 0l5.159 5.159m-1.5-1.5l1.409-1.409a2.25 2.25 0 013.182 0l2.909 2.909M3.75 21h16.5A2.25 2.25 0 0022.5 18.75V5.25A2.25 2.25 0 0020.25 3H3.75A2.25 2.25 0 001.5 5.25v13.5A2.25 2.25 0 003.75 21z" />
              </svg>
            </div>
            <div className="cart-item-details">
              <strong>{item.name}</strong>
              <div className="cart-item-qty">Qty: {item.quantity}</div>
              <button className="cart-item-remove" onClick={() => handleRemove(item.product_id)}>
                Remove
              </button>
            </div>
            <div className="cart-item-price">${item.line_total}</div>
          </div>
        ))}
      </div>
      <div className="cart-sidebar">
        <div className="cart-subtotal">
          Subtotal ({cart.items.length} {cart.items.length === 1 ? "item" : "items"}): <span>${cart.total}</span>
        </div>
        <button className="btn-checkout" onClick={() => navigate("/checkout")}>
          Proceed to Checkout
        </button>
      </div>
    </div>
  );
}
