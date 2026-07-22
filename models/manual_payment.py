from sqlalchemy import Column, String, DateTime, Numeric, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base
import uuid

class ManualPayment(Base):
    __tablename__ = "manual_payments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True)
    
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), default="USD")
    network = Column(String(30), nullable=False)
    
    phone_used = Column(String(30), nullable=True)
    transaction_id = Column(String(100), nullable=True)
    proof_note = Column(Text, nullable=True)
    screenshot_url = Column(String(500), nullable=True)
    
    status = Column(String(20), default="pending", nullable=False, index=True)
    
    admin_note = Column(Text, nullable=True)
    reviewed_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user = relationship("User", foreign_keys=[user_id])
    reviewer = relationship("User", foreign_keys=[reviewed_by])
