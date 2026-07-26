from pydantic import BaseModel, field_validator
from typing import Optional, List
from decimal import Decimal

class ServiceResponse(BaseModel):
    id: str
    platform: str
    name: str
    description: Optional[str]
    rate_per_1k: float
    min_qty: int
    max_qty: int
    provider: Optional[str]
    avg_speed: Optional[str]
    is_instant: bool
    quality_badge: Optional[str]
    refill_enabled: bool
    cancel_enabled: bool
    category_name: Optional[str] = None

    class Config:
        from_attributes = True

class PlaceOrderRequest(BaseModel):
    service_id: str
    link: str
    quantity: int

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v):
        if v < 1:
            raise ValueError("Quantity must be at least 1")
        return v

    @field_validator("link")
    @classmethod
    def validate_link(cls, v):
        if not v.strip():
            raise ValueError("Link cannot be empty")
        return v.strip()

class OrderResponse(BaseModel):
    id: str
    order_number: int
    service_name: str
    platform: str
    link: str
    quantity: int
    charge: float
    status: str
    start_count: int
    remains: int
    created_at: str
    updated_at: str
    is_admin_power: bool

    class Config:
        from_attributes = True

class AdminPowerOrderRequest(BaseModel):
    service_id: str
    account_link: str
    quantity: int
    note: Optional[str] = "Personal account boost"

class ServiceCreateRequest(BaseModel):
    platform: str
    name: str
    description: Optional[str] = None
    rate_per_1k: float
    cost_per_1k: Optional[float] = None
    min_qty: int = 10
    max_qty: int = 100000
    provider: Optional[str] = None
    provider_service_id: Optional[str] = None
    avg_speed: Optional[str] = None
    is_instant: bool = False
    quality_badge: Optional[str] = None
    refill_enabled: bool = False
    cancel_enabled: bool = False
    is_active: bool = True
    is_recommended: bool = False

class ServiceUpdateRequest(BaseModel):
    platform: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    rate_per_1k: Optional[float] = None
    cost_per_1k: Optional[float] = None
    min_qty: Optional[int] = None
    max_qty: Optional[int] = None
    provider: Optional[str] = None
    provider_service_id: Optional[str] = None
    avg_speed: Optional[str] = None
    is_instant: Optional[bool] = None
    quality_badge: Optional[str] = None
    refill_enabled: Optional[bool] = None
    cancel_enabled: Optional[bool] = None
    is_active: Optional[bool] = None
    is_recommended: Optional[bool] = None
