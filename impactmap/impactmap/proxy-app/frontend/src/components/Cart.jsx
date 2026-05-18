// components/Cart.jsx
// Shows current cart contents. Remove items. Link to Checkout.
// API calls: fetchCart (GET /cart), removeFromCart (DELETE /cart/item/:id)

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
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

  if (loading) return <p>Loading cart...</p>;

  return (
    <div className="cart">
      <h2>Your Cart</h2>
      {cart.items.length === 0 ? (
        <p>Your cart is empty.</p>
      ) : (
        <>
          {cart.items.map((item) => (
            <div key={item.product_id} className="cart-item">
              <div>
                <strong>{item.name}</strong>
                <span> × {item.quantity}</span>
              </div>
              <div>
                <span>${item.line_total}</span>
                <button onClick={() => handleRemove(item.product_id)}>Remove</button>
              </div>
            </div>
          ))}
          <div className="cart-total">Total: ${cart.total}</div>
          <button className="checkout-btn" onClick={() => navigate("/checkout")}>
            Proceed to Checkout
          </button>
        </>
      )}
    </div>
  );
}
