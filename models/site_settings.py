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
    default_provider = Column(String(50), default="jap")
    auto_sync_services = Column(Boolean, default=True)

    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
