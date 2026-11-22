from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Table, Text,
                        UniqueConstraint, Index)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base, JSONType


def now() -> datetime:
    return datetime.now(timezone.utc)


def new_token() -> str:
    return secrets.token_urlsafe(12)


collection_recipes = Table(
    "collection_recipes", Base.metadata,
    Column("collection_id", ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True),
    Column("recipe_id", ForeignKey("recipes.id", ondelete="CASCADE"), primary_key=True),
)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[Optional[str]] = mapped_column(String(100))
    bio: Mapped[Optional[str]] = mapped_column(Text)
    is_private: Mapped[bool] = mapped_column(Boolean, default=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    units: Mapped[str] = mapped_column(String(10), default="original")  # original | metric | imperial
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Recipe(Base):
    __tablename__ = "recipes"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[Optional[str]] = mapped_column(Text)
    image_url: Mapped[Optional[str]] = mapped_column(Text)
    source_url: Mapped[Optional[str]] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(20), default="manual")
    author: Mapped[Optional[str]] = mapped_column(String(200))
    servings: Mapped[Optional[float]] = mapped_column(Float)
    servings_text: Mapped[Optional[str]] = mapped_column(String(100))
    prep_time: Mapped[Optional[int]] = mapped_column(Integer)
    cook_time: Mapped[Optional[int]] = mapped_column(Integer)
    total_time: Mapped[Optional[int]] = mapped_column(Integer)
    ingredients: Mapped[list] = mapped_column(JSONType, default=list)
    steps: Mapped[list] = mapped_column(JSONType, default=list)
    categories: Mapped[list] = mapped_column(JSONType, default=list)
    cuisine: Mapped[Optional[str]] = mapped_column(String(80))
    nutrition: Mapped[Optional[dict]] = mapped_column(JSONType, nullable=True)
    components: Mapped[Optional[list]] = mapped_column(JSONType, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    favorite: Mapped[bool] = mapped_column(Boolean, default=False)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    share_token: Mapped[str] = mapped_column(String(32), default=new_token, unique=True, index=True)
    copied_from_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    last_cooked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)

    owner: Mapped[User] = relationship(lazy="joined")
    collections: Mapped[list["Collection"]] = relationship(secondary=collection_recipes, back_populates="recipes")


class Collection(Base):
    __tablename__ = "collections"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    icon: Mapped[Optional[str]] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    recipes: Mapped[list[Recipe]] = relationship(secondary=collection_recipes, back_populates="collections")


class ShoppingItem(Base):
    __tablename__ = "shopping_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    key: Mapped[str] = mapped_column(String(300))
    quantity: Mapped[Optional[float]] = mapped_column(Float)
    unit: Mapped[Optional[str]] = mapped_column(String(30))
    aisle: Mapped[str] = mapped_column(String(40), default="Other")
    checked: Mapped[bool] = mapped_column(Boolean, default=False)
    sources: Mapped[list] = mapped_column(JSONType, default=list)
    position: Mapped[int] = mapped_column(Integer, default=0)
    ha_uid: Mapped[Optional[str]] = mapped_column(String(100))  # matching Home Assistant to-do item
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class JournalEntry(Base):
    __tablename__ = "journal_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    recipe_id: Mapped[Optional[int]] = mapped_column(ForeignKey("recipes.id", ondelete="SET NULL"))
    text: Mapped[Optional[str]] = mapped_column(Text)
    rating: Mapped[Optional[int]] = mapped_column(Integer)
    photo_url: Mapped[Optional[str]] = mapped_column(Text)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True)
    cooked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)

    owner: Mapped[User] = relationship(lazy="joined")
    recipe: Mapped[Optional[Recipe]] = relationship(lazy="joined")


class Follow(Base):
    __tablename__ = "follows"
    __table_args__ = (UniqueConstraint("follower_id", "followee_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    followee_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


Index("ix_recipes_owner_title", Recipe.owner_id, Recipe.title)
