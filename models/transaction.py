from sqlalchemy import Column, String, DateTime, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import uuid

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    type = Column(String(50), nullable=False, index=True)
    # deposit, order_charge, refund, admin_adjustment, referral_bonus, admin_power

    amount = Column(Numeric(10, 2), nullable=False)  # Positive = credit, negative = debit
    balance_before = Column(Numeric(10, 2), nullable=True)
    balance_after = Column(Numeric(10, 2), nullable=True)
    currency = Column(String(10), default="USD")

    # Payment details
    payment_method = Column(String(50), nullable=True)  # paystack, pawapay, manual, admin
    payment_reference = Column(String(255), nullable=True)
    payment_country = Column(String(100), nullable=True)

    status = Column(String(20), default="completed", nullable=False)
    # pending, completed, failed, refunded

    description = Column(Text, nullable=True)
    metadata_ = Column("metadata", JSONB, default={})

    order_id = Column(UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="transactions")
