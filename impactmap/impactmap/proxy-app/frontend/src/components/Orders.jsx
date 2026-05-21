import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { fetchOrder, fetchOrders } from "../api/client";

export function OrderConfirmation() {
  const { orderId } = useParams();
  const [order, setOrder] = useState(null);

  useEffect(() => {
    fetchOrder(orderId).then((r) => setOrder(r.data));
  }, [orderId]);

  if (!order) return <p className="loading">Loading order...</p>;

  return (
    <div className="order-detail">
      <div className="order-success-banner">Order placed successfully!</div>
      <div className="order-info">
        <h2>Order Details</h2>
        <p>Order ID: <strong><code>{order.id}</code></strong></p>
        <p>Status: <span className={`status-badge ${order.status}`}>{order.status}</span></p>
        <p>Shipping to: <strong>{order.shipping_addr}</strong></p>
      </div>
      <table className="order-items-table">
        <thead>
          <tr>
            <th>Product</th>
            <th>Quantity</th>
            <th>Unit Price</th>
            <th>Total</th>
          </tr>
        </thead>
        <tbody>
          {order.items.map((item) => (
            <tr key={item.product_id}>
              <td>{item.product_name}</td>
              <td>{item.quantity}</td>
              <td>${item.unit_price}</td>
              <td>${(item.quantity * item.unit_price).toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <td colSpan="3">Order Total</td>
            <td>${order.total_amount}</td>
          </tr>
        </tfoot>
      </table>
      <Link to="/orders" className="back-link">← Back to Orders</Link>
    </div>
  );
}

export function OrderHistory() {
  const [orders, setOrders] = useState([]);

  useEffect(() => {
    fetchOrders().then((r) => setOrders(r.data));
  }, []);

  return (
    <div className="orders-page">
      <h2>Your Orders</h2>
      {orders.length === 0 ? (
        <div className="cart-empty">
          <p>No orders yet.</p>
          <Link to="/">Start shopping</Link>
        </div>
      ) : (
        orders.map((o) => (
          <div key={o.id} className="order-card">
            <div className="order-card-header">
              <span>Order # <code>{o.id.slice(0, 8)}...</code></span>
              <span>{new Date(o.created_at).toLocaleDateString()}</span>
              <span className={`status-badge ${o.status}`}>{o.status}</span>
            </div>
            <div className="order-card-body">
              <div className="order-total">${o.total_amount}</div>
              <Link to={`/orders/${o.id}`}>View Details →</Link>
            </div>
          </div>
        ))
      )}
    </div>
  );
}
