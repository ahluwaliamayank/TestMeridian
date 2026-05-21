"""
models.py — SQLAlchemy ORM models for the ImpactMap proxy app.

Keeping models in a separate file gives the analyzer a clean place to
build the model-name → table-name registry before it scans the routes.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Column, String, Text, Numeric, Integer, ForeignKey,
    DateTime, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id         = Column(String(300), primary_key=True, default=uuid.uuid4)
    email      = Column(String(200), nullable=False, unique=True)
    name       = Column(String(200), nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    cart_items = relationship("CartItem", back_populates="user", cascade="all, delete-orphan")
    orders     = relationship("Order", back_populates="user")


class Product(Base):
    __tablename__ = "products"

    id          = Column(String(300), primary_key=True, default=uuid.uuid4)
    name        = Column(String(200), nullable=False)
    description = Column(Text)
    price       = Column(Numeric(10, 2), nullable=False)
    stock_qty   = Column(Integer, nullable=False, default=0)
    category    = Column(String(100))
    image_url   = Column(String(500))
    created_at  = Column(DateTime, server_default=func.now())

    cart_items  = relationship("CartItem", back_populates="product")
    order_items = relationship("OrderItem", back_populates="product")


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id"),)

    id         = Column(String(300), primary_key=True, default=uuid.uuid4)
    user_id    = Column(String(300), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(300), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    quantity   = Column(Integer, nullable=False, default=1)
    added_at   = Column(DateTime, server_default=func.now())

    user    = relationship("User", back_populates="cart_items")
    product = relationship("Product", back_populates="cart_items")


class Order(Base):
    __tablename__ = "orders"

    id            = Column(String(300), primary_key=True, default=uuid.uuid4)
    user_id       = Column(String(300), ForeignKey("users.id"), nullable=False)
    status        = Column(String(50), nullable=False, default="pending")
    total_amount  = Column(Numeric(10, 2), nullable=False)
    shipping_addr = Column(Text)
    created_at    = Column(DateTime, server_default=func.now())

    user  = relationship("User", back_populates="orders")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")


class OrderItem(Base):
    __tablename__ = "order_items"

    id         = Column(String(300), primary_key=True, default=uuid.uuid4)
    order_id   = Column(String(300), ForeignKey("orders.id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(300), ForeignKey("products.id"), nullable=False)
    quantity   = Column(Integer, nullable=False)
    unit_price = Column(Numeric(10, 2), nullable=False)

    order   = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")
