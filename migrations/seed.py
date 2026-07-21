"""
Run this after first deploy to seed the database with default data.
Usage: python migrations/seed.py
"""
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select
from database import Base
from models.user import User
from models.service import Service, ServiceCategory
from models.site_settings import SiteSettings
from models.admin_log import AdminActivityLog
from models.order import Order
from models.transaction import Transaction
from utils.security import hash_password, generate_referral_code, generate_api_key
from config import settings
import uuid

engine = create_async_engine(settings.DATABASE_URL)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

async def seed():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with AsyncSessionLocal() as db:
        # ── Site Settings ──────────────────────────────────────────────────
        existing_settings = (await db.execute(select(SiteSettings))).scalar_one_or_none()
        if not existing_settings:
            db.add(SiteSettings(
                id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                site_name="BOASTLIB",
                site_description="The cheapest SMM panel with real-time delivery.",
                currency="USD",
                currency_symbol="$",
                support_email="support@boastlib.com",
                default_provider="jap"
            ))
            print("✅ Site settings created")

        # ── Admin User ─────────────────────────────────────────────────────
        existing_admin = (await db.execute(
            select(User).where(User.email == "admin@boastlib.com")
        )).scalar_one_or_none()

        if not existing_admin:
            admin_user = User(
                email="admin@boastlib.com",
                password_hash=hash_password("Admin123!"),
                full_name="BOASTLIB Admin",
                role="super_admin",
                status="active",
                balance=999999.00,
                referral_code=generate_referral_code(),
                api_key=generate_api_key(),
                is_developer=True
            )
            db.add(admin_user)
            print("✅ Admin user created: admin@boastlib.com / Admin123!")

        # ── Sample Services ────────────────────────────────────────────────
        existing_services = (await db.execute(select(Service))).scalars().all()
        if not existing_services:
            services = [
                # Instagram
                Service(platform="instagram", name="Instagram Followers — High Retention", rate_per_1k=1.20, cost_per_1k=0.80, min_qty=100, max_qty=100000, avg_speed="Instant", is_instant=True, quality_badge="High Quality", provider="jap", provider_service_id="1", refill_enabled=True, is_active=True),
                Service(platform="instagram", name="Instagram Followers — Real & Active", rate_per_1k=2.50, cost_per_1k=1.80, min_qty=100, max_qty=50000, avg_speed="1-2 hours", is_instant=False, quality_badge="Best Seller", provider="peakerr", provider_service_id="2", refill_enabled=True, is_active=True),
                Service(platform="instagram", name="Instagram Post Likes", rate_per_1k=0.30, cost_per_1k=0.10, min_qty=50, max_qty=500000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="3", is_active=True),
                Service(platform="instagram", name="Instagram Video Views", rate_per_1k=0.10, cost_per_1k=0.05, min_qty=500, max_qty=10000000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="4", is_active=True),
                Service(platform="instagram", name="Instagram Story Views", rate_per_1k=0.15, cost_per_1k=0.08, min_qty=100, max_qty=1000000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="5", is_active=True),
                Service(platform="instagram", name="Instagram Comments — Custom", rate_per_1k=8.00, cost_per_1k=5.00, min_qty=10, max_qty=5000, avg_speed="1-2 hours", provider="peakerr", provider_service_id="6", is_active=True),
                # TikTok
                Service(platform="tiktok", name="TikTok Followers — Fast", rate_per_1k=0.80, cost_per_1k=0.50, min_qty=100, max_qty=200000, avg_speed="Instant", is_instant=True, quality_badge="High Quality", provider="jap", provider_service_id="10", refill_enabled=True, is_active=True),
                Service(platform="tiktok", name="TikTok Video Likes", rate_per_1k=0.20, cost_per_1k=0.08, min_qty=50, max_qty=1000000, avg_speed="Instant", is_instant=True, quality_badge="Best Seller", provider="jap", provider_service_id="11", is_active=True),
                Service(platform="tiktok", name="TikTok Video Views", rate_per_1k=0.05, cost_per_1k=0.01, min_qty=1000, max_qty=100000000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="12", is_active=True),
                Service(platform="tiktok", name="TikTok Shares", rate_per_1k=1.50, cost_per_1k=1.00, min_qty=100, max_qty=50000, avg_speed="1-2 hours", provider="peakerr", provider_service_id="13", is_active=True),
                # YouTube
                Service(platform="youtube", name="YouTube Views — High Retention", rate_per_1k=1.50, cost_per_1k=1.00, min_qty=500, max_qty=5000000, avg_speed="Gradual", is_instant=False, quality_badge="High Quality", provider="peakerr", provider_service_id="20", is_active=True),
                Service(platform="youtube", name="YouTube Subscribers", rate_per_1k=3.00, cost_per_1k=2.00, min_qty=100, max_qty=50000, avg_speed="1-2 hours", provider="jap", provider_service_id="21", refill_enabled=True, is_active=True),
                Service(platform="youtube", name="YouTube Likes", rate_per_1k=0.80, cost_per_1k=0.50, min_qty=50, max_qty=100000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="22", is_active=True),
                # Facebook
                Service(platform="facebook", name="Facebook Page Likes", rate_per_1k=1.00, cost_per_1k=0.60, min_qty=100, max_qty=100000, avg_speed="1-2 hours", provider="jap", provider_service_id="30", refill_enabled=True, is_active=True),
                Service(platform="facebook", name="Facebook Post Likes", rate_per_1k=0.50, cost_per_1k=0.20, min_qty=100, max_qty=500000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="31", is_active=True),
                Service(platform="facebook", name="Facebook Followers", rate_per_1k=1.20, cost_per_1k=0.80, min_qty=100, max_qty=100000, avg_speed="1-2 hours", provider="peakerr", provider_service_id="32", is_active=True),
                # Twitter/X
                Service(platform="twitter", name="Twitter Followers", rate_per_1k=1.50, cost_per_1k=1.00, min_qty=100, max_qty=100000, avg_speed="1-2 hours", provider="jap", provider_service_id="40", refill_enabled=True, is_active=True),
                Service(platform="twitter", name="Twitter Likes", rate_per_1k=0.40, cost_per_1k=0.20, min_qty=50, max_qty=500000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="41", is_active=True),
                # Telegram
                Service(platform="telegram", name="Telegram Channel Members", rate_per_1k=1.00, cost_per_1k=0.60, min_qty=100, max_qty=500000, avg_speed="1-2 hours", provider="jap", provider_service_id="50", is_active=True),
                Service(platform="telegram", name="Telegram Post Views", rate_per_1k=0.05, cost_per_1k=0.01, min_qty=1000, max_qty=100000000, avg_speed="Instant", is_instant=True, provider="jap", provider_service_id="51", is_active=True),
                # Spotify
                Service(platform="spotify", name="Spotify Plays", rate_per_1k=0.50, cost_per_1k=0.30, min_qty=1000, max_qty=10000000, avg_speed="Gradual", provider="jap", provider_service_id="60", is_active=True),
                Service(platform="spotify", name="Spotify Followers", rate_per_1k=2.00, cost_per_1k=1.50, min_qty=100, max_qty=50000, avg_speed="1-2 hours", provider="jap", provider_service_id="61", is_active=True),
                # Discord
                Service(platform="discord", name="Discord Server Members", rate_per_1k=5.00, cost_per_1k=3.50, min_qty=10, max_qty=10000, avg_speed="1-2 hours", provider="peakerr", provider_service_id="70", is_active=True),
            ]
            for s in services:
                db.add(s)
            print(f"✅ {len(services)} sample services created")

        await db.commit()
        print("\n🚀 BOASTLIB database seeded successfully!")
        print("   Admin: admin@boastlib.com / Admin123!")
        print("   Change the admin password after first login!")

if __name__ == "__main__":
    asyncio.run(seed())
