import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchOrder, fetchOrders } from "../api/client";

export function OrderConfirmation() {
  const { orderId } = useParams();
  const [order, setOrder] = useState(null);

  useEffect(() => {
    fetchOrder(orderId).then((r) => setOrder(r.data));
  }, [orderId]);

  if (!order) return <p>Loading order...</p>;

  return (
    <div className="order-confirmation">
      <h2>Order Confirmed ✓</h2>
      <p>Order ID: <code>{order.id}</code></p>
      <p>Status: <strong>{order.status}</strong></p>
      <p>Total: <strong>${order.total_amount}</strong></p>
      <p>Shipping to: {order.shipping_addr}</p>
      <h3>Items</h3>
      {order.items.map((item) => (
        <div key={item.product_id} className="order-item">
          <span>{item.product_name} × {item.quantity}</span>
          <span>${item.unit_price}</span>
        </div>
      ))}
      <Link to="/orders">View all orders →</Link>
    </div>
  );
}

export function OrderHistory() {
  const [orders, setOrders] = useState([]);

  useEffect(() => {
    fetchOrders().then((r) => setOrders(r.data));
  }, []);

  return (
    <div className="order-history">
      <h2>Order History</h2>
      {orders.length === 0 ? (
        <p>No orders yet.</p>
      ) : (
        orders.map((o) => (
          <div key={o.id} className="order-row">
            <span><code>{o.id.slice(0, 8)}…</code></span>
            <span>{o.status}</span>
            <span>${o.total_amount}</span>
            <span>{new Date(o.created_at).toLocaleDateString()}</span>
            <Link to={`/orders/${o.id}`}>View →</Link>
          </div>
        ))
      )}
    </div>
  );
}
