"""
BOASTLIB Developer API
Standard SMM panel API v2 format — compatible with all SMM panel integrations
"""
from fastapi import APIRouter, Depends, HTTPException, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from database import get_db
from models.user import User
from models.order import Order
from models.service import Service
from models.transaction import Transaction
from decimal import Decimal
import uuid
from utils.pagination import get_next_order_number
from utils.pricing import calculate_charge

router = APIRouter(prefix="/api/v2", tags=["developer-api"])

async def get_api_user(key: str, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.api_key == key, User.is_developer == True))
    user = result.scalar_one_or_none()
    if not user or user.status in ["suspended", "banned"]:
        raise HTTPException(status_code=401, detail={"error": "Invalid API key"})
    return user

@router.post("")
async def api_v2(
    key: str = Form(...),
    action: str = Form(...),
    service: str = Form(None),
    link: str = Form(None),
    quantity: int = Form(None),
    order: str = Form(None),
    orders: str = Form(None),
    db: AsyncSession = Depends(get_db)
):
    user = await get_api_user(key, db)

    if action == "services":
        result = await db.execute(select(Service).where(Service.is_active == True))
        services = result.scalars().all()
        return [
            {
                "service": str(s.id),
                "name": s.name,
                "type": s.platform,
                "category": s.platform.capitalize(),
                "rate": str(s.rate_per_1k),
                "min": str(s.min_qty),
                "max": str(s.max_qty),
                "dripfeed": False,
                "refill": s.refill_enabled,
                "cancel": s.cancel_enabled,
            }
            for s in services
        ]

    elif action == "add":
        if not service or not link or not quantity:
            return {"error": "Missing required parameters: service, link, quantity"}

        # Get service
        svc_result = await db.execute(
            select(Service).where(Service.id == uuid.UUID(service), Service.is_active == True)
        )
        svc = svc_result.scalar_one_or_none()
        if not svc:
            return {"error": "Service not found"}

        if quantity < svc.min_qty or quantity > svc.max_qty:
            return {"error": f"Quantity must be between {svc.min_qty} and {svc.max_qty}"}

        charge = calculate_charge(svc.rate_per_1k, quantity)

        if user.balance < charge:
            return {"error": "Insufficient balance"}

        user.balance -= charge

        # Get next order number
        order_num = await get_next_order_number(db)

        new_order = Order(
            order_number=order_num,
            user_id=user.id,
            service_id=svc.id,
            link=link,
            quantity=quantity,
            charge=charge,
            provider=svc.provider,
            status="pending"
        )
        db.add(new_order)
        await db.commit()

        return {"order": order_num}

    elif action == "status":
        if not order:
            return {"error": "Order ID required"}

        result = await db.execute(
            select(Order).where(Order.order_number == int(order), Order.user_id == user.id)
        )
        o = result.scalar_one_or_none()
        if not o:
            return {"error": "Order not found"}

        status_map = {
            "pending": "Pending",
            "processing": "In progress",
            "in_progress": "In progress",
            "completed": "Completed",
            "partial": "Partial",
            "cancelled": "Cancelled"
        }

        return {
            "charge": str(o.charge),
            "start_count": str(o.start_count),
            "status": status_map.get(o.status, "Pending"),
            "remains": str(o.remains),
            "currency": "USD"
        }

    elif action == "multistatus":
        if not orders:
            return {"error": "Order IDs required"}

        order_nums = [int(n.strip()) for n in orders.split(",") if n.strip().isdigit()]
        result = await db.execute(
            select(Order).where(Order.order_number.in_(order_nums), Order.user_id == user.id)
        )
        order_list = result.scalars().all()

        status_map = {
            "pending": "Pending", "processing": "In progress",
            "in_progress": "In progress", "completed": "Completed",
            "partial": "Partial", "cancelled": "Cancelled"
        }

        return {
            str(o.order_number): {
                "charge": str(o.charge),
                "start_count": str(o.start_count),
                "status": status_map.get(o.status, "Pending"),
                "remains": str(o.remains),
                "currency": "USD"
            }
            for o in order_list
        }

    elif action == "balance":
        return {
            "balance": str(float(user.balance)),
            "currency": "USD"
        }

    elif action == "cancel":
        if not orders:
            return {"error": "Order ID required"}

        result = await db.execute(
            select(Order, Service)
            .join(Service, Order.service_id == Service.id)
            .where(Order.order_number == int(orders), Order.user_id == user.id)
        )
        row = result.first()
        if not row:
            return {"error": "Order not found"}

        o, svc = row

        if not svc.cancel_enabled:
            return {"error": "Order cannot be cancelled"}

        if o.status != "pending":
            return {"error": "Only pending orders can be cancelled"}

        # Refund
        user.balance += o.charge
        o.status = "cancelled"
        await db.commit()
        return {"cancel": [{"order": o.order_number, "cancel": {"1": "success"}}]}

    else:
        return {"error": f"Unknown action: {action}"}
