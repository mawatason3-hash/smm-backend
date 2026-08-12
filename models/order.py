from sqlalchemy import Column, String, Boolean, DateTime, Integer, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import uuid

class Order(Base):
    __tablename__ = "orders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    order_number = Column(Integer, unique=True, nullable=False)  # Sequential: 10001, 10002...
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    service_id = Column(UUID(as_uuid=True), ForeignKey("services.id"), nullable=False)
    placed_by_admin = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)  # If admin placed for user

    # Order details
    link = Column(Text, nullable=False)
    quantity = Column(Integer, nullable=False)
    charge = Column(Numeric(10, 4), nullable=False)
    provider_cost = Column(Numeric(10, 4), nullable=True)  # What we paid provider

    # Status tracking
    status = Column(String(30), default="pending", nullable=False, index=True)
    status_details = Column(Text, nullable=True)
    # pending, processing, in_progress, completed, partial, cancelled, refunded, error

    # Progress
    start_count = Column(Integer, default=0)
    remains = Column(Integer, default=0)

    # Provider tracking
    provider = Column(String(50), nullable=True)
    provider_order_id = Column(String(100), nullable=True)

    # Admin Power flag
    is_admin_power = Column(Boolean, default=False)

    # Metadata
    notes = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="orders", foreign_keys=[user_id])
    service = relationship("Service", back_populates="orders")
    tickets = relationship("Ticket", back_populates="order")
