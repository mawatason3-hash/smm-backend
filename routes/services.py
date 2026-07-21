from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from database import get_db
from models.service import Service, ServiceCategory
from models.user import User
from schemas.order import ServiceCreateRequest, ServiceUpdateRequest
from middleware.auth_middleware import get_current_user, get_current_admin
from services.provider_service import get_provider_services
from utils.pricing import markup_price
import uuid

router = APIRouter(prefix="/api/services", tags=["services"])

@router.get("")
async def list_services(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    platform: str = Query(None),
    category: str = Query(None),
    search: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    query = select(Service).where(Service.is_active == True)

    if platform:
        query = query.where(Service.platform == platform.lower())
    if search:
        query = query.where(Service.name.ilike(f"%{search}%"))

    query = query.order_by(Service.sort_order, Service.platform, Service.name)
    query = query.offset((page - 1) * limit).limit(limit)

    result = await db.execute(query)
    services = result.scalars().all()

    return [
        {
            "id": str(s.id),
            "platform": s.platform,
            "name": s.name,
            "description": s.description,
            "rate_per_1k": float(s.rate_per_1k),
            "min_qty": s.min_qty,
            "max_qty": s.max_qty,
            "avg_speed": s.avg_speed,
            "is_instant": s.is_instant,
            "quality_badge": s.quality_badge,
            "refill_enabled": s.refill_enabled,
            "cancel_enabled": s.cancel_enabled,
        }
        for s in services
    ]

@router.get("/platforms")
async def get_platforms(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Service.platform).where(Service.is_active == True).distinct()
    )
    platforms = [row[0] for row in result.all()]
    return {"platforms": platforms}

# Admin routes
@router.get("/admin/all")
async def admin_list_services(
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_current_admin),
    platform: str = Query(None),
    status: str = Query(None),
    search: str = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200)
):
    query = select(Service)

    if platform:
        query = query.where(Service.platform == platform.lower())
    if status == "active":
        query = query.where(Service.is_active == True)
    elif status == "inactive":
        query = query.where(Service.is_active == False)
    if search:
        query = query.where(Service.name.ilike(f"%{search}%"))

    from sqlalchemy import func
    count_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = count_result.scalar()

    query = query.order_by(Service.platform, Service.sort_order).offset((page - 1) * limit).limit(limit)
    result = await db.execute(query)
    services = result.scalars().all()

    return {
        "items": [
            {
                "id": str(s.id),
                "platform": s.platform,
                "name": s.name,
                "rate_per_1k": float(s.rate_per_1k),
                "cost_per_1k": float(s.cost_per_1k) if s.cost_per_1k else None,
                "min_qty": s.min_qty,
                "max_qty": s.max_qty,
                "provider": s.provider,
                "provider_service_id": s.provider_service_id,
                "avg_speed": s.avg_speed,
                "is_active": s.is_active,
                "refill_enabled": s.refill_enabled,
                "cancel_enabled": s.cancel_enabled,
            }
            for s in services
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }

@router.post("/admin")
async def create_service(
    data: ServiceCreateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    service = Service(**data.model_dump())
    db.add(service)
    await db.commit()
    return {"id": str(service.id), "message": "Service created"}

@router.put("/admin/{service_id}")
async def update_service(
    service_id: str,
    data: ServiceUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Service).where(Service.id == uuid.UUID(service_id)))
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    for key, value in data.model_dump(exclude_none=True).items():
        setattr(service, key, value)

    await db.commit()
    return {"message": "Service updated"}

@router.delete("/admin/{service_id}")
async def delete_service(
    service_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Service).where(Service.id == uuid.UUID(service_id)))
    service = result.scalar_one_or_none()
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    await db.delete(service)
    await db.commit()
    return {"message": "Service deleted"}

@router.post("/admin/sync/{provider}")
async def sync_provider_services(
    provider: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    """Sync services from a provider API"""
    services = await get_provider_services(provider)

    if not services:
        raise HTTPException(status_code=400, detail=f"Could not fetch services from {provider}")

    synced = 0
    for svc in services:
        # Check if service already exists by provider_service_id
        existing = await db.execute(
            select(Service).where(
                Service.provider == provider,
                Service.provider_service_id == str(svc.get("service", ""))
            )
        )
        existing_service = existing.scalar_one_or_none()

        if existing_service:
            # Update provider cost and keep markup consistent
            provider_cost = float(svc.get("rate", 0))
            existing_service.cost_per_1k = provider_cost
            existing_service.rate_per_1k = float(markup_price(provider_cost))
        else:
            # Create new
            provider_cost = float(svc.get("rate", 0))
            new_service = Service(
                platform=svc.get("category", "other").lower().split(" ")[0],
                name=svc.get("name", ""),
                rate_per_1k=float(markup_price(provider_cost)),
                cost_per_1k=provider_cost,
                min_qty=int(svc.get("min", 10)),
                max_qty=int(svc.get("max", 100000)),
                provider=provider,
                provider_service_id=str(svc.get("service", "")),
                avg_speed="1-2 hours",
                is_active=False  # Admin activates manually
            )
            db.add(new_service)
            synced += 1

    await db.commit()
    return {"message": f"Synced {synced} new services from {provider}", "total_from_provider": len(services)}
