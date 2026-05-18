"""
ImpactMap Proxy App — FastAPI Backend (SQLAlchemy ORM edition)

All database access goes through SQLAlchemy session + ORM models.
The ImpactMap analyzer detects model class names in each route handler
and maps them to their __tablename__ to build the endpoint→table graph.
"""

import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import User, Product, CartItem, Order, OrderItem

app = FastAPI(title="ImpactMap Proxy API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEMO_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


# ── Products ──────────────────────────────────────────────────────────────────

@app.get("/products")
def list_products(
    category: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List products with optional category filter and name/description search."""
    query = db.query(Product)
    if category:
        query = query.filter(Product.category == category)
    if search:
        query = query.filter(
            Product.name.ilike(f"%{search}%") | Product.description.ilike(f"%{search}%")
        )
    products = query.order_by(Product.created_at.desc()).all()
    return [
        {
            "id": str(p.id), "name": p.name, "description": p.description,
            "price": float(p.price), "stock_qty": p.stock_qty, "category": p.category,
        }
        for p in products
    ]


@app.get("/products/{product_id}")
def get_product(product_id: str, db: Session = Depends(get_db)):
    """Fetch a single product by ID."""
    product = db.query(Product).filter(Product.id == uuid.UUID(product_id)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    return {
        "id": str(product.id), "name": product.name, "description": product.description,
        "price": float(product.price), "stock_qty": product.stock_qty, "category": product.category,
    }


# ── Cart ──────────────────────────────────────────────────────────────────────

@app.get("/cart")
def get_cart(db: Session = Depends(get_db)):
    """Return all cart items for the demo user, joining Product for details."""
    items = (
        db.query(CartItem)
        .filter(CartItem.user_id == DEMO_USER_ID)
        .join(CartItem.product)
        .order_by(CartItem.added_at)
        .all()
    )
    result = []
    total = 0.0
    for item in items:
        line_total = float(item.product.price) * item.quantity
        total += line_total
        result.append({
            "id": str(item.id),
            "product_id": str(item.product_id),
            "name": item.product.name,
            "price": float(item.product.price),
            "quantity": item.quantity,
            "line_total": round(line_total, 2),
        })
    return {"items": result, "total": round(total, 2)}


class AddToCartRequest(BaseModel):
    product_id: str
    quantity: int = 1


@app.post("/cart/add")
def add_to_cart(body: AddToCartRequest, db: Session = Depends(get_db)):
    """
    Add a product to the cart.
    Reads Product to validate stock, then upserts CartItem.
    """
    product = db.query(Product).filter(Product.id == uuid.UUID(body.product_id)).first()
    if not product:
        raise HTTPException(status_code=404, detail="Product not found")
    if product.stock_qty < body.quantity:
        raise HTTPException(status_code=400, detail="Insufficient stock")

    existing = (
        db.query(CartItem)
        .filter(CartItem.user_id == DEMO_USER_ID, CartItem.product_id == uuid.UUID(body.product_id))
        .first()
    )
    if existing:
        existing.quantity += body.quantity
    else:
        db.add(CartItem(
            user_id=DEMO_USER_ID,
            product_id=uuid.UUID(body.product_id),
            quantity=body.quantity,
        ))
    db.commit()
    return {"status": "added"}


@app.delete("/cart/item/{product_id}")
def remove_from_cart(product_id: str, db: Session = Depends(get_db)):
    """Remove a specific item from the cart by product ID."""
    item = (
        db.query(CartItem)
        .filter(CartItem.user_id == DEMO_USER_ID, CartItem.product_id == uuid.UUID(product_id))
        .first()
    )
    if item:
        db.delete(item)
        db.commit()
    return {"status": "removed"}


# ── Orders ────────────────────────────────────────────────────────────────────

class PlaceOrderRequest(BaseModel):
    shipping_addr: str


@app.post("/orders")
def place_order(body: PlaceOrderRequest, db: Session = Depends(get_db)):
    """
    Place an order (all within one transaction):
      1. Query CartItem + Product (read)
      2. Validate stock on each Product (read)
      3. Create Order (write)
      4. Create OrderItem per line (write)
      5. Decrement Product.stock_qty (write)
      6. Delete CartItem rows (write)
    """
    cart_items = (
        db.query(CartItem)
        .filter(CartItem.user_id == DEMO_USER_ID)
        .join(CartItem.product)
        .all()
    )
    if not cart_items:
        raise HTTPException(status_code=400, detail="Cart is empty")

    for item in cart_items:
        if item.product.stock_qty < item.quantity:
            raise HTTPException(
                status_code=400,
                detail=f"Insufficient stock for {item.product.name}",
            )

    total = sum(float(item.product.price) * item.quantity for item in cart_items)

    order = Order(
        user_id=DEMO_USER_ID,
        status="confirmed",
        total_amount=round(total, 2),
        shipping_addr=body.shipping_addr,
    )
    db.add(order)
    db.flush()  # get order.id before commit

    for item in cart_items:
        db.add(OrderItem(
            order_id=order.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=item.product.price,
        ))
        item.product.stock_qty -= item.quantity
        db.delete(item)

    db.commit()
    return {"order_id": str(order.id), "total": round(total, 2)}


@app.get("/orders")
def list_orders(db: Session = Depends(get_db)):
    """List all orders for the demo user, newest first."""
    orders = (
        db.query(Order)
        .filter(Order.user_id == DEMO_USER_ID)
        .order_by(Order.created_at.desc())
        .all()
    )
    return [
        {
            "id": str(o.id), "status": o.status,
            "total_amount": float(o.total_amount),
            "shipping_addr": o.shipping_addr,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]


@app.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    """Fetch a single order with its line items, joining Product for names."""
    order = db.query(Order).filter(Order.id == uuid.UUID(order_id)).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    items = (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order.id)
        .join(OrderItem.product)
        .all()
    )
    return {
        "id": str(order.id),
        "status": order.status,
        "total_amount": float(order.total_amount),
        "shipping_addr": order.shipping_addr,
        "created_at": order.created_at.isoformat(),
        "items": [
            {
                "product_id": str(i.product_id),
                "product_name": i.product.name,
                "quantity": i.quantity,
                "unit_price": float(i.unit_price),
            }
            for i in items
        ],
    }
