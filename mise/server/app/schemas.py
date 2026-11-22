from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=40, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=200)
    email: Optional[str] = None
    display_name: Optional[str] = None


class LoginIn(BaseModel):
    username: str
    password: str


class UserPatch(BaseModel):
    display_name: Optional[str] = None
    bio: Optional[str] = None
    email: Optional[str] = None
    is_private: Optional[bool] = None
    units: Optional[Literal["original", "metric", "imperial"]] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=200)


class IngredientIn(BaseModel):
    raw: str
    group: Optional[str] = None


class StepIn(BaseModel):
    text: str
    section: Optional[str] = None


class RecipeIn(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    description: Optional[str] = None
    image_url: Optional[str] = None
    source_url: Optional[str] = None
    author: Optional[str] = None
    servings: Optional[float] = None
    servings_text: Optional[str] = None
    prep_time: Optional[int] = None
    cook_time: Optional[int] = None
    total_time: Optional[int] = None
    ingredients: list[IngredientIn] = []
    steps: list[StepIn] = []
    categories: Optional[list[str]] = None
    cuisine: Optional[str] = None
    notes: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=0, le=5)
    favorite: bool = False
    is_public: bool = True


class RecipePatch(BaseModel):
    favorite: Optional[bool] = None
    rating: Optional[int] = Field(default=None, ge=0, le=5)
    notes: Optional[str] = None
    is_public: Optional[bool] = None
    categories: Optional[list[str]] = None
    title: Optional[str] = None
    image_url: Optional[str] = None


class ImportURLIn(BaseModel):
    url: str
    save: bool = True


class ImportHTMLIn(BaseModel):
    url: str
    html: str = Field(max_length=8_000_000)
    save: bool = True


class ImportTextIn(BaseModel):
    text: str
    title: Optional[str] = None
    source_type: Literal["text", "voice"] = "text"
    save: bool = True


class CollectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    icon: Optional[str] = None


class ShoppingFromRecipeIn(BaseModel):
    recipe_id: int
    servings: Optional[float] = None
    scale: Optional[float] = None
    ingredient_indexes: Optional[list[int]] = None


class ShoppingItemIn(BaseModel):
    text: str


class ShoppingItemPatch(BaseModel):
    checked: Optional[bool] = None
    text: Optional[str] = None
    aisle: Optional[str] = None


class JournalIn(BaseModel):
    recipe_id: Optional[int] = None
    text: Optional[str] = None
    rating: Optional[int] = Field(default=None, ge=0, le=5)
    photo_url: Optional[str] = None
    is_public: bool = True
    cooked_at: Optional[datetime] = None
