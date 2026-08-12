from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from database import get_db
from models.user import User
from models.order import Order
from models.service import Service
from models.transaction import Transaction
from schemas.order import PlaceOrderRequest, AdminPowerOrderRequest, OrderResponse
from middleware.auth_middleware import get_current_user, get_current_admin
from services.provider_service import place_provider_order, check_provider_order_status
from decimal import Decimal
import uuid
from utils.pagination import get_next_order_number
from utils.pricing import calculate_charge, calculate_provider_cost

router = APIRouter(prefix="/api/orders", tags=["orders"])

@router.post("")
async def place_order(
    data: PlaceOrderRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Get service
    result = await db.execute(
        select(Service).where(Service.id == uuid.UUID(data.service_id), Service.is_active == True)
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found or inactive")

    # Validate quantity
    if data.quantity < service.min_qty:
        raise HTTPException(status_code=400, detail=f"Minimum quantity is {service.min_qty}")
    if data.quantity > service.max_qty:
        raise HTTPException(status_code=400, detail=f"Maximum quantity is {service.max_qty}")

    # Calculate charge
    charge = calculate_charge(service.rate_per_1k, data.quantity)

    # Check balance
    if current_user.balance < charge:
        raise HTTPException(
            status_code=402,
            detail=f"Insufficient balance. Required: ${charge}, Available: ${current_user.balance}"
        )

    # Deduct balance
    current_user.balance -= charge

    # Create order
    order_number = await get_next_order_number(db)
    order = Order(
        order_number=order_number,
        user_id=current_user.id,
        service_id=service.id,
        link=data.link,
        quantity=data.quantity,
        charge=charge,
        provider_cost=calculate_provider_cost(service.cost_per_1k or service.rate_per_1k, data.quantity),
        provider=service.provider,
        status="pending"
    )
    db.add(order)
    await db.flush()

    # Create transaction
    transaction = Transaction(
        user_id=current_user.id,
        type="order_charge",
        amount=-float(charge),
        balance_before=float(current_user.balance + charge),
        balance_after=float(current_user.balance),
        status="completed",
        description=f"Order #{order_number} - {service.name}",
        order_id=order.id
    )
    db.add(transaction)

    # Submit to provider
    if service.provider and service.provider_service_id:
        provider_result = await place_provider_order(
            service.provider,
            service.provider_service_id,
            data.link,
            data.quantity
        )
        if provider_result and "order" in provider_result:
            order.provider_order_id = str(provider_result["order"])
            order.status = "processing"

    await db.commit()

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "charge": float(order.charge),
        "balance_remaining": float(current_user.balance),
        "message": "Order placed successfully"
    }

@router.get("")
async def get_my_orders(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    status: str = Query(None),
    platform: str = Query(None)
):
    query = (
        select(Order, Service)
        .join(Service, Order.service_id == Service.id)
        .where(Order.user_id == current_user.id)
    )

    if status:
        query = query.where(Order.status == status)
    if platform:
        query = query.where(Service.platform == platform)

    # Count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar()

    # Paginate
    query = query.order_by(desc(Order.created_at)).offset((page - 1) * limit).limit(limit)
    results = (await db.execute(query)).all()

    orders = []
    for order, service in results:
        orders.append({
            "id": str(order.id),
            "order_number": order.order_number,
            "service_name": service.name,
            "platform": service.platform,
            "link": order.link,
            "quantity": order.quantity,
            "charge": float(order.charge),
            "status": order.status,
            "status_details": order.status_details,
            "start_count": order.start_count,
            "remains": order.remains,
            "is_admin_power": order.is_admin_power,
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
        })

    return {
        "items": orders,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }

@router.get("/{order_id}")
async def get_order(
    order_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(Order, Service)
        .join(Service)
        .where(Order.id == uuid.UUID(order_id), Order.user_id == current_user.id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")

    order, service = row

    # Check live status from provider
    if order.provider_order_id and order.status in ["processing", "in_progress"]:
        live_status = await check_provider_order_status(order.provider, order.provider_order_id)
        if live_status:
            order.start_count = int(live_status.get("start_count", order.start_count))
            order.remains = int(live_status.get("remains", order.remains))
            await db.commit()

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "service_name": service.name,
        "platform": service.platform,
        "link": order.link,
        "quantity": order.quantity,
        "charge": float(order.charge),
        "status": order.status,
        "start_count": order.start_count,
        "remains": order.remains,
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
    }

# ADMIN POWER — Free boost for admin's personal accounts
@router.post("/admin-power")
async def admin_power_boost(
    data: AdminPowerOrderRequest,
    current_user: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    # Get service
    result = await db.execute(
        select(Service).where(Service.id == uuid.UUID(data.service_id), Service.is_active == True)
    )
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    # Validate quantity
    if data.quantity < service.min_qty:
        raise HTTPException(status_code=400, detail=f"Minimum quantity is {service.min_qty}")

    # Provider cost (what we pay, not what we charge)
    provider_cost = calculate_provider_cost(service.cost_per_1k or service.rate_per_1k, data.quantity)

    # Create order with $0 charge (free for admin)
    order_number = await get_next_order_number(db)
    order = Order(
        order_number=order_number,
        user_id=current_user.id,
        service_id=service.id,
        link=data.account_link,
        quantity=data.quantity,
        charge=Decimal("0.00"),  # FREE for admin
        provider_cost=float(provider_cost),
        provider=service.provider,
        status="pending",
        is_admin_power=True,
        notes=data.note or "ADMIN Power — Personal account boost"
    )
    db.add(order)

    # Update admin power usage counter
    current_user.admin_power_used += 1

    await db.flush()

    # Submit to provider at provider's cost
    if service.provider and service.provider_service_id:
        provider_result = await place_provider_order(
            service.provider,
            service.provider_service_id,
            data.account_link,
            data.quantity
        )
        if provider_result and "order" in provider_result:
            order.provider_order_id = str(provider_result["order"])
            order.status = "processing"

    # Log it
    transaction = Transaction(
        user_id=current_user.id,
        type="admin_power",
        amount=0.00,
        balance_before=float(current_user.balance),
        balance_after=float(current_user.balance),
        status="completed",
        description=f"ADMIN Power boost #{order_number} - {service.name} (Provider cost: ${float(provider_cost):.4f})",
        order_id=order.id
    )
    db.add(transaction)
    await db.commit()

    return {
        "id": str(order.id),
        "order_number": order.order_number,
        "status": order.status,
        "provider_cost": float(provider_cost),
        "your_cost": 0.00,
        "message": "⚡ ADMIN Power boost placed successfully!"
    }
