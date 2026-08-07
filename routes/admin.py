from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc, and_, update, delete
from database import get_db
from models.user import User
from models.order import Order
from models.transaction import Transaction
from models.service import Service
from models.site_settings import SiteSettings
from models.admin_log import AdminActivityLog
from middleware.auth_middleware import get_current_admin
from services.provider_service import check_provider_balance
from datetime import datetime, timezone, timedelta
import uuid

router = APIRouter(prefix="/api/admin", tags=["admin"])

KNOWN_PLATFORMS = [
    'instagram', 'tiktok', 'youtube', 'facebook', 'twitter', 'x',
    'telegram', 'spotify', 'discord', 'twitch', 'linkedin',
    'threads', 'snapchat', 'pinterest', 'reddit', 'whatsapp'
]


def extract_platform(raw_category: str, service_name: str = "") -> str:
    combined = f"{raw_category} {service_name}".lower()
    for platform_name in KNOWN_PLATFORMS:
        if platform_name in combined:
            return platform_name
    return 'other'

@router.get("/dashboard")
async def admin_dashboard(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Total users
    total_users = (await db.execute(select(func.count(User.id)))).scalar()

    # New users today
    new_today = (await db.execute(
        select(func.count(User.id)).where(User.created_at >= today_start)
    )).scalar()

    # Revenue today (completed deposits)
    revenue_today = (await db.execute(
        select(func.sum(Transaction.amount)).where(
            Transaction.type == "deposit",
            Transaction.status == "completed",
            Transaction.created_at >= today_start
        )
    )).scalar() or 0

    # Revenue this month
    revenue_month = (await db.execute(
        select(func.sum(Transaction.amount)).where(
            Transaction.type == "deposit",
            Transaction.status == "completed",
            Transaction.created_at >= month_start
        )
    )).scalar() or 0

    # All time revenue
    revenue_all = (await db.execute(
        select(func.sum(Transaction.amount)).where(
            Transaction.type == "deposit",
            Transaction.status == "completed"
        )
    )).scalar() or 0

    # Orders today
    orders_today = (await db.execute(
        select(func.count(Order.id)).where(Order.created_at >= today_start)
    )).scalar()

    # Pending orders
    pending_orders = (await db.execute(
        select(func.count(Order.id)).where(Order.status == "pending")
    )).scalar()

    # Recent users
    recent_users_result = await db.execute(
        select(User).order_by(desc(User.created_at)).limit(10)
    )
    recent_users = [
        {
            "id": str(u.id),
            "full_name": u.full_name,
            "email": u.email,
            "balance": float(u.balance),
            "status": u.status,
            "created_at": u.created_at.isoformat()
        }
        for u in recent_users_result.scalars().all()
    ]

    # Recent transactions
    recent_tx_result = await db.execute(
        select(Transaction, User)
        .join(User, Transaction.user_id == User.id)
        .order_by(desc(Transaction.created_at))
        .limit(10)
    )
    recent_transactions = [
        {
            "id": str(tx.id),
            "user_name": user.full_name,
            "type": tx.type,
            "payment_method": tx.payment_method,
            "amount": float(tx.amount),
            "status": tx.status,
            "created_at": tx.created_at.isoformat()
        }
        for tx, user in recent_tx_result.all()
    ]

    return {
        "stats": {
            "total_users": total_users,
            "new_today": new_today,
            "orders_today": orders_today,
            "pending_orders": pending_orders,
            "revenue_today": float(revenue_today),
            "revenue_month": float(revenue_month),
            "revenue_all_time": float(revenue_all),
        },
        "recent_users": recent_users,
        "recent_transactions": recent_transactions
    }

@router.get("/provider-balance/{provider}")
async def get_provider_balance(
    provider: str,
    admin: User = Depends(get_current_admin),
):
    if provider != "wizsmm":
        raise HTTPException(status_code=400, detail="Unsupported provider")

    result = await check_provider_balance(provider)
    if not result:
        raise HTTPException(status_code=404, detail="Provider not configured or unavailable")

    return {
        "provider": provider,
        "balance": result.get("balance", "0"),
        "currency": result.get("currency", "USD")
    }

@router.post("/services/purge-provider")
async def purge_provider_services(
    data: dict,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    provider = data.get("provider")
    if not provider:
        raise HTTPException(status_code=400, detail="provider required")

    service_ids_result = await db.execute(
        select(Service.id).where(Service.provider == provider)
    )
    service_ids = [row[0] for row in service_ids_result.all()]

    if service_ids:
        order_ids_result = await db.execute(
            select(Order.id).where(Order.service_id.in_(service_ids))
        )
        order_ids = [row[0] for row in order_ids_result.all()]

        if order_ids:
            await db.execute(
                update(Transaction)
                .where(Transaction.order_id.in_(order_ids))
                .values(order_id=None)
            )

        await db.execute(delete(Order).where(Order.service_id.in_(service_ids)))

    stmt = delete(Service).where(Service.provider == provider)
    result = await db.execute(stmt)
    await db.commit()

    log = AdminActivityLog(
        admin_id=admin.id,
        action="purge_provider_services",
        target_type="service",
        target_id="bulk",
        details={"provider": provider, "count": result.rowcount}
    )
    db.add(log)
    await db.commit()

    return {"message": f"Deleted {result.rowcount} services from {provider}"}

@router.get("/users")
async def list_users(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    search: str = Query(None),
    status: str = Query(None),
    role: str = Query(None)
):
    query = select(User)

    if search:
        query = query.where(
            (User.email.ilike(f"%{search}%")) | (User.full_name.ilike(f"%{search}%"))
        )
    if status:
        query = query.where(User.status == status)
    if role:
        query = query.where(User.role == role)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(desc(User.created_at)).offset((page - 1) * limit).limit(limit)
    users = (await db.execute(query)).scalars().all()

    return {
        "items": [
            {
                "id": str(u.id),
                "full_name": u.full_name,
                "email": u.email,
                "phone": u.phone,
                "country": u.country,
                "balance": float(u.balance),
                "role": u.role,
                "status": u.status,
                "is_developer": u.is_developer,
                "created_at": u.created_at.isoformat(),
                "last_login_at": u.last_login_at.isoformat() if u.last_login_at else None,
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@router.get("/users/{user_id}")
async def get_user(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Get order stats
    total_orders = (await db.execute(
        select(func.count(Order.id)).where(Order.user_id == user.id)
    )).scalar()

    total_spent = (await db.execute(
        select(func.sum(Transaction.amount)).where(
            Transaction.user_id == user.id,
            Transaction.type == "deposit",
            Transaction.status == "completed"
        )
    )).scalar() or 0

    # Recent orders
    recent_orders_result = await db.execute(
        select(Order, Service)
        .join(Service)
        .where(Order.user_id == user.id)
        .order_by(desc(Order.created_at))
        .limit(10)
    )
    recent_orders = [
        {
            "order_number": o.order_number,
            "service": s.name,
            "status": o.status,
            "charge": float(o.charge),
            "created_at": o.created_at.isoformat()
        }
        for o, s in recent_orders_result.all()
    ]

    # Recent transactions
    recent_tx_result = await db.execute(
        select(Transaction)
        .where(Transaction.user_id == user.id)
        .order_by(desc(Transaction.created_at))
        .limit(10)
    )
    recent_tx = [
        {
            "id": str(tx.id),
            "type": tx.type,
            "amount": float(tx.amount),
            "status": tx.status,
            "description": tx.description,
            "created_at": tx.created_at.isoformat()
        }
        for tx in recent_tx_result.scalars().all()
    ]

    return {
        "user": {
            "id": str(user.id),
            "full_name": user.full_name,
            "email": user.email,
            "phone": user.phone,
            "country": user.country,
            "role": user.role,
            "status": user.status,
            "balance": float(user.balance),
            "referral_code": user.referral_code,
            "is_developer": user.is_developer,
            "admin_power_used": user.admin_power_used,
            "created_at": user.created_at.isoformat(),
            "last_login_at": user.last_login_at.isoformat() if user.last_login_at else None,
        },
        "stats": {
            "total_orders": total_orders,
            "total_spent": float(total_spent),
        },
        "recent_orders": recent_orders,
        "recent_transactions": recent_tx
    }

@router.put("/users/{user_id}")
async def update_user(
    user_id: str,
    data: dict,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    allowed_fields = ["role", "status", "full_name", "phone", "country", "is_developer"]
    for field in allowed_fields:
        if field in data:
            setattr(user, field, data[field])

    await db.commit()

    # Log action
    log = AdminActivityLog(
        admin_id=admin.id,
        action="update_user",
        target_type="user",
        target_id=user_id,
        details=data
    )
    db.add(log)
    await db.commit()

    return {"message": "User updated"}

@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.status = "suspended"
    log = AdminActivityLog(admin_id=admin.id, action="suspend_user", target_type="user", target_id=user_id)
    db.add(log)
    await db.commit()
    return {"message": "User suspended"}


@router.post("/services/fix-platforms")
async def fix_service_platforms(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Service))
    services = result.scalars().all()
    fixed = 0
    for service in services:
        corrected_platform = extract_platform(service.platform, service.name)
        if service.platform != corrected_platform:
            service.platform = corrected_platform
            fixed += 1
    await db.commit()
    return {"message": f"Fixed platform field on {fixed} services"}


@router.post("/services/bulk-action")
async def bulk_service_action(
    data: dict,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    action = data.get("action")
    service_ids = data.get("service_ids")
    provider = data.get("provider")

    if action not in ("activate", "deactivate", "delete"):
        raise HTTPException(400, "Invalid action")
    if not service_ids and not provider:
        raise HTTPException(400, "Must provide service_ids or provider")

    if service_ids:
        ids = [uuid.UUID(sid) for sid in service_ids]
        condition = Service.id.in_(ids)
    elif provider == "all":
        condition = None
    else:
        condition = Service.provider == provider

    if action == "delete":
        stmt = delete(Service)
        if condition is not None:
            stmt = stmt.where(condition)
    else:
        stmt = update(Service).values(is_active=(action == "activate"))
        if condition is not None:
            stmt = stmt.where(condition)

    result = await db.execute(stmt)
    await db.commit()

    log = AdminActivityLog(
        admin_id=admin.id,
        action=f"bulk_{action}_services",
        target_type="service",
        target_id="bulk",
        details={"provider": provider, "count": result.rowcount, "explicit_ids": bool(service_ids)}
    )
    db.add(log)
    await db.commit()

    return {"message": f"{action.capitalize()}d {result.rowcount} services", "count": result.rowcount}

@router.post("/users/{user_id}/activate")
async def activate_user(
    user_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.status = "active"
    log = AdminActivityLog(admin_id=admin.id, action="activate_user", target_type="user", target_id=user_id)
    db.add(log)
    await db.commit()
    return {"message": "User activated"}

@router.get("/transactions")
async def list_transactions(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    type: str = Query(None),
    status: str = Query(None)
):
    query = select(Transaction, User).join(User, Transaction.user_id == User.id)

    if type:
        query = query.where(Transaction.type == type)
    if status:
        query = query.where(Transaction.status == status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(desc(Transaction.created_at)).offset((page - 1) * limit).limit(limit)
    results = (await db.execute(query)).all()

    return {
        "items": [
            {
                "id": str(tx.id),
                "user_name": user.full_name,
                "user_email": user.email,
                "type": tx.type,
                "amount": float(tx.amount),
                "payment_method": tx.payment_method,
                "status": tx.status,
                "description": tx.description,
                "created_at": tx.created_at.isoformat()
            }
            for tx, user in results
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@router.get("/settings")
async def get_settings(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(SiteSettings))
    settings_obj = result.scalar_one_or_none()
    if not settings_obj:
        raise HTTPException(status_code=404, detail="Settings not found")

    return {
        "site_name": settings_obj.site_name,
        "site_description": settings_obj.site_description,
        "currency": settings_obj.currency,
        "currency_symbol": settings_obj.currency_symbol,
        "telegram_link": settings_obj.telegram_link,
        "whatsapp_link": settings_obj.whatsapp_link,
        "whatsapp_support": settings_obj.whatsapp_support,
        "telegram_support": settings_obj.telegram_support,
        "liberia_mtn_number": settings_obj.liberia_mtn_number,
        "liberia_orange_number": settings_obj.liberia_orange_number,
        "manual_payment_instructions": settings_obj.manual_payment_instructions,
        "manual_payment_time": settings_obj.manual_payment_time,
        "support_email": settings_obj.support_email,
        "maintenance_mode": settings_obj.maintenance_mode,
        "registration_open": settings_obj.registration_open,
        "default_provider": settings_obj.default_provider,
        "auto_sync_services": settings_obj.auto_sync_services,
    }

@router.put("/settings")
async def update_settings(
    data: dict,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(SiteSettings))
    settings_obj = result.scalar_one_or_none()
    if not settings_obj:
        raise HTTPException(status_code=404, detail="Settings not found")

    allowed = [
        "site_name", "site_description", "telegram_link",
        "whatsapp_link", "support_email", "maintenance_mode",
        "registration_open", "default_provider", "auto_sync_services"
    ]
    # allow manual payment settings to be updated
    allowed += [
        "whatsapp_support", "telegram_support", "liberia_mtn_number", "liberia_orange_number",
        "manual_payment_instructions", "manual_payment_time"
    ]
    for field in allowed:
        if field in data:
            setattr(settings_obj, field, data[field])

    log = AdminActivityLog(admin_id=admin.id, action="update_settings", target_type="settings")
    db.add(log)
    await db.commit()
    return {"message": "Settings updated"}

@router.get("/orders")
async def admin_list_orders(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(25, ge=1, le=100),
    status: str = Query(None),
    platform: str = Query(None)
):
    from models.order import Order
    from models.service import Service
    query = (
        select(Order, User, Service)
        .join(User, Order.user_id == User.id)
        .join(Service, Order.service_id == Service.id)
    )
    if status:
        query = query.where(Order.status == status)
    if platform:
        query = query.where(Service.platform == platform)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(desc(Order.created_at)).offset((page - 1) * limit).limit(limit)
    results = (await db.execute(query)).all()

    return {
        "items": [
            {
                "id": str(order.id),
                "order_number": order.order_number,
                "user_name": user.full_name,
                "user_email": user.email,
                "service_name": service.name,
                "platform": service.platform,
                "link": order.link,
                "quantity": order.quantity,
                "charge": float(order.charge),
                "status": order.status,
                "is_admin_power": order.is_admin_power,
                "created_at": order.created_at.isoformat(),
            }
            for order, user, service in results
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@router.get("/activity-log")
async def get_activity_log(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100)
):
    query = select(AdminActivityLog, User).join(User, AdminActivityLog.admin_id == User.id)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(desc(AdminActivityLog.created_at)).offset((page - 1) * limit).limit(limit)
    results = (await db.execute(query)).all()

    return {
        "items": [
            {
                "id": str(log.id),
                "admin_name": user.full_name,
                "admin_email": user.email,
                "action": log.action,
                "target_type": log.target_type,
                "target_id": log.target_id,
                "details": log.details,
                "created_at": log.created_at.isoformat()
            }
            for log, user in results
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@router.get("/health-detail")
async def get_health_details(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Get detailed platform health status"""
    from sqlalchemy import text
    
    now = datetime.now(timezone.utc)
    health = {
        "api": "operational",
        "database": "error",
        "timestamp": now.isoformat()
    }
    
    try:
        await db.execute(text("SELECT 1"))
        health["database"] = "connected"
    except Exception:
        health["database"] = "error"
    
    return health
