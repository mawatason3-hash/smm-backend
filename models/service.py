from sqlalchemy import Column, String, Boolean, DateTime, Integer, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import uuid

class Service(Base):
    __tablename__ = "services"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform = Column(String(50), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Pricing
    rate_per_1k = Column(Numeric(10, 4), nullable=False)  # Your price to customer
    cost_per_1k = Column(Numeric(10, 4), nullable=True)   # Provider cost

    # Quantity limits
    min_qty = Column(Integer, nullable=False, default=10)
    max_qty = Column(Integer, nullable=False, default=100000)

    # Provider info
    provider = Column(String(50), nullable=True)  # wizsmm only
    provider_service_id = Column(String(50), nullable=True)

    # Speed & quality
    avg_speed = Column(String(50), nullable=True)  # "Instant", "1-2 hours", etc.
    is_instant = Column(Boolean, default=False)
    quality_badge = Column(String(50), nullable=True)  # "High Quality", "Best Seller"

    # Features
    refill_enabled = Column(Boolean, default=False)
    cancel_enabled = Column(Boolean, default=False)

    is_active = Column(Boolean, default=True, index=True)
    is_recommended = Column(Boolean, default=False, nullable=False)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    orders = relationship("Order", back_populates="service")
