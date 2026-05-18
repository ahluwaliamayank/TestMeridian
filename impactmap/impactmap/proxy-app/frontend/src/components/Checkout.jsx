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
    <div className="checkout">
      <h2>Checkout</h2>
      <div className="checkout-summary">
        <h3>Order Summary</h3>
        {cart.items.map((item) => (
          <div key={item.product_id} className="summary-item">
            <span>{item.name} × {item.quantity}</span>
            <span>${item.line_total}</span>
          </div>
        ))}
        <div className="summary-total">Total: ${cart.total}</div>
      </div>
      <div className="shipping-form">
        <label>Shipping Address</label>
        <textarea
          rows={3}
          value={shippingAddr}
          onChange={(e) => setShippingAddr(e.target.value)}
          placeholder="123 Main St, City, Country"
        />
        <button onClick={handlePlaceOrder} disabled={placing}>
          {placing ? "Placing order..." : "Place Order"}
        </button>
      </div>
    </div>
  );
}
