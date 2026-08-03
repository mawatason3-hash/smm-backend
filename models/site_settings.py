from sqlalchemy import Column, String, Boolean, DateTime, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from database import Base
import uuid

class SiteSettings(Base):
    __tablename__ = "site_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.UUID("00000000-0000-0000-0000-000000000001"))
    site_name = Column(String(100), default="BOASTLIB")
    site_description = Column(Text, default="The cheapest SMM panel with real-time delivery.")
    logo_url = Column(String(500), default="/logo.svg")
    favicon_url = Column(String(500), default="/favicon.ico")
    currency = Column(String(10), default="USD")
    currency_symbol = Column(String(5), default="$")
    telegram_link = Column(String(500), default="")
    whatsapp_link = Column(String(500), default="")
    support_email = Column(String(255), default="support@boastlib.com")
    maintenance_mode = Column(Boolean, default=False)
    registration_open = Column(Boolean, default=True)

    # Provider settings
    default_provider = Column(String(50), default="wizsmm")
    auto_sync_services = Column(Boolean, default=True)

    # Liberia Mobile Money Settings
    liberia_mtn_number = Column(String(50), default="0555166954")
    liberia_orange_number = Column(String(50), default="")
    whatsapp_support = Column(String(50), default="+250792405593")
    telegram_support = Column(String(100), default="https://t.me/boastlib_support")
    manual_payment_instructions = Column(Text, default="Send the amount to the number above and submit the transaction ID from your SMS receipt. Note: you will see USD on the site; the actual charge may be in local currency (KES) depending on the payment provider.")
    manual_payment_time = Column(String(50), default="4-10 mins")

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
