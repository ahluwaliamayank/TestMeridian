// src/App.jsx
import { BrowserRouter, Routes, Route, NavLink, Link } from "react-router-dom";
import ProductList from "./components/ProductList";
import Cart from "./components/Cart";
import Checkout from "./components/Checkout";
import { OrderConfirmation, OrderHistory } from "./components/Orders";
import "./index.css";

export default function App() {
  return (
    <BrowserRouter>
      <nav className="navbar">
        <Link to="/" className="navbar-logo">Amazone</Link>
        <div className="navbar-links">
          <NavLink to="/" end>Products</NavLink>
          <NavLink to="/cart">Cart</NavLink>
          <NavLink to="/orders">Orders</NavLink>
        </div>
      </nav>
      <main>
        <Routes>
          <Route path="/" element={<ProductList />} />
          <Route path="/cart" element={<Cart />} />
          <Route path="/checkout" element={<Checkout />} />
          <Route path="/orders" element={<OrderHistory />} />
          <Route path="/orders/:orderId" element={<OrderConfirmation />} />
        </Routes>
      </main>
    </BrowserRouter>
  );
}
