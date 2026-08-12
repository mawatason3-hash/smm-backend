import asyncio
from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from database import AsyncSessionLocal
from models.order import Order
from services.provider_service import check_provider_order_status, map_provider_status

from config import settings

SYNC_INTERVAL_SECONDS = getattr(settings, 'ORDER_SYNC_INTERVAL_SECONDS', 300)
IN_PROGRESS_STATUSES = {'pending', 'processing', 'in_progress'}

async def refresh_order_status(order: Order, db: AsyncSession) -> bool:
    if not order.provider or not order.provider_order_id:
        return False

    live_status = await check_provider_order_status(order.provider, order.provider_order_id)
    if not live_status:
        return False

    provider_status = live_status.get('status') or live_status.get('status_text') or live_status.get('status_str')
    mapped_status = map_provider_status(str(provider_status or '').strip())
    if mapped_status == order.status and 'start_count' not in live_status and 'remains' not in live_status:
        return False

    updated = False
    if mapped_status != order.status:
        order.status = mapped_status
        updated = True
        if mapped_status in {'completed', 'partial', 'cancelled', 'refunded'}:
            order.completed_at = datetime.now(timezone.utc)

    if 'start_count' in live_status:
        try:
            order.start_count = int(live_status.get('start_count', order.start_count))
            updated = True
        except Exception:
            pass
    if 'remains' in live_status:
        try:
            order.remains = int(live_status.get('remains', order.remains))
            updated = True
        except Exception:
            pass

    if live_status:
        order.status_details = str(live_status)
    return updated

async def sync_pending_orders():
    async with AsyncSessionLocal() as db:
        query = select(Order).where(Order.status.in_(IN_PROGRESS_STATUSES))
        result = await db.execute(query)
        orders = result.scalars().all()
        for order in orders:
            try:
                updated = await refresh_order_status(order, db)
                if updated:
                    db.add(order)
            except Exception:
                continue
        await db.commit()

async def _order_sync_loop():
    while True:
        await sync_pending_orders()
        await asyncio.sleep(SYNC_INTERVAL_SECONDS)

def start_order_status_sync():
    loop = asyncio.get_running_loop()
    task = loop.create_task(_order_sync_loop())
    return task

def stop_order_status_sync(task: asyncio.Task):
    if task and not task.done():
        task.cancel()
