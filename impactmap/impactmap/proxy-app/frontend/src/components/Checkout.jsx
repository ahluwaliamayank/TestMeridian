// components/Checkout.jsx
// Collects shipping address. Shows cart summary. Places order.
// API calls: fetchCart (GET /cart), placeOrder (POST /orders)

import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { fetchCart, placeOrder } from "../api/client";

export default function Checkout() {
  const [cart, setCart] = useState({ items: [], total: 0 });
  const [shippingAddr, setShippingAddr] = useState("");
  const [placing, setPlacing] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    fetchCart().then((r) => setCart(r.data));
  }, []);

  const handlePlaceOrder = async () => {
    if (!shippingAddr.trim()) return alert("Enter a shipping address");
    setPlacing(true);
    try {
      const res = await placeOrder(shippingAddr);
      navigate(`/orders/${res.data.order_id}`);
    } catch (e) {
      alert(e.response?.data?.detail || "Order failed");
      setPlacing(false);
    }
  };

  return (
    <div className="checkout-page">
      <div className="checkout-shipping">
        <h2>Shipping Address</h2>
        <label htmlFor="shipping-addr">Enter your shipping address</label>
        <textarea
          id="shipping-addr"
          rows={4}
          value={shippingAddr}
          onChange={(e) => setShippingAddr(e.target.value)}
          placeholder="123 Main St, City, State, ZIP, Country"
        />
      </div>
      <div className="checkout-summary">
        <h3>Order Summary</h3>
        {cart.items.map((item) => (
          <div key={item.product_id} className="summary-item">
            <span>{item.name} x{item.quantity}</span>
            <span>${item.line_total}</span>
          </div>
        ))}
        <hr className="summary-divider" />
        <div className="summary-total">
          <span>Order Total</span>
          <span>${cart.total}</span>
        </div>
        <button
          className="btn-place-order"
          onClick={handlePlaceOrder}
          disabled={placing || !shippingAddr.trim()}
        >
          {placing ? "Placing order..." : "Place Order"}
        </button>
      </div>
    </div>
  );
}
