from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.order import Order
from services.provider_service import map_provider_status
import uuid

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])


@router.post("/provider")
async def provider_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    data = await request.json()
    # Expected fields: provider, provider_order_id, status, start_count, remains
    provider = data.get('provider')
    provider_order_id = data.get('provider_order_id')
    status = data.get('status')
    if not provider or not provider_order_id or status is None:
        raise HTTPException(status_code=400, detail="Missing fields")

    # Find order by provider_order_id
    result = await db.execute(select(Order).where(Order.provider_order_id == str(provider_order_id)))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    mapped = map_provider_status(str(status))
    order.status = mapped
    if 'start_count' in data:
        try:
            order.start_count = int(data.get('start_count', order.start_count))
        except Exception:
            pass
    if 'remains' in data:
        try:
            order.remains = int(data.get('remains', order.remains))
        except Exception:
            pass

    order.status_details = str(data)
    await db.commit()

    return {"ok": True}
