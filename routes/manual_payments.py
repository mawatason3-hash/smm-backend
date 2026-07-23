from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from database import get_db
from models.user import User
from models.manual_payment import ManualPayment
from models.transaction import Transaction
from models.admin_log import AdminActivityLog
from models.site_settings import SiteSettings
from middleware.auth_middleware import get_current_user, get_current_admin
from schemas.payment import InitiatePaymentRequest
from pydantic import BaseModel
from datetime import datetime, timezone
from decimal import Decimal
import uuid

router = APIRouter(prefix="/api/payments", tags=["payments"])

class ManualPaymentRequest(BaseModel):
    amount: float
    network: str
    phone_used: str
    transaction_id: str
    proof_note: str = None

class AdminApproveRequest(BaseModel):
    admin_note: str = None

class AdminRejectRequest(BaseModel):
    admin_note: str

@router.post("/manual/submit")
async def submit_manual_payment(
    data: ManualPaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if data.amount < 1:
        raise HTTPException(status_code=400, detail="Minimum deposit is $1")
    
    if data.network not in ["MTN_LIBERIA", "ORANGE_LIBERIA"]:
        raise HTTPException(status_code=400, detail="Invalid network")
    
    if not data.phone_used:
        raise HTTPException(status_code=400, detail="Phone number required")
    
    if not data.transaction_id:
        raise HTTPException(status_code=400, detail="Transaction ID required")
    
    payment = ManualPayment(
        id=uuid.uuid4(),
        user_id=current_user.id,
        amount=Decimal(str(data.amount)),
        currency="USD",
        network=data.network,
        phone_used=data.phone_used,
        transaction_id=data.transaction_id,
        proof_note=data.proof_note or "",
        status="pending"
    )
    
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    
    return {
        "id": str(payment.id),
        "message": "Submitted! Admin will credit within 1-2 hours"
    }

@router.get("/manual/my-requests")
async def get_my_manual_payments(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ManualPayment)
        .where(ManualPayment.user_id == current_user.id)
        .order_by(desc(ManualPayment.created_at))
    )
    
    payments = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(p.id),
                "amount": float(p.amount),
                "network": p.network,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
                "admin_note": p.admin_note
            }
            for p in payments
        ]
    }

@router.get("/manual/settings")
async def get_manual_payment_settings(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SiteSettings))
    settings = result.scalar_one_or_none()
    
    if not settings:
        return {
            "mtn_number": "0555166954",
            "orange_number": "",
            "whatsapp": "+250792405593",
            "telegram": "https://t.me/boastlib_support",
            "instructions": "Send the amount to the number above and submit the transaction ID from your SMS receipt.",
            "processing_time": "15-30 mins"
        }
    
    return {
        "mtn_number": settings.liberia_mtn_number,
        "orange_number": settings.liberia_orange_number,
        "whatsapp": settings.whatsapp_support,
        "telegram": settings.telegram_support,
        "instructions": settings.manual_payment_instructions,
        "processing_time": settings.manual_payment_time
    }

admin_router = APIRouter(prefix="/api/admin", tags=["admin-manual-payments"])

@admin_router.get("/manual-payments")
async def list_manual_payments(
    status: str = Query("pending", regex="^(pending|approved|rejected|all)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    query = select(ManualPayment, User).join(User, ManualPayment.user_id == User.id)
    
    if status != "all":
        query = query.where(ManualPayment.status == status)
    
    if status == "all":
        total_result = await db.execute(select(func.count(ManualPayment.id)))
    else:
        total_result = await db.execute(select(func.count(ManualPayment.id)).where(ManualPayment.status == status))
    total = total_result.scalar()

    pending_result = await db.execute(select(func.count(ManualPayment.id)).where(ManualPayment.status == 'pending'))
    approved_result = await db.execute(select(func.count(ManualPayment.id)).where(ManualPayment.status == 'approved'))
    rejected_result = await db.execute(select(func.count(ManualPayment.id)).where(ManualPayment.status == 'rejected'))

    pending_count = pending_result.scalar() or 0
    approved_count = approved_result.scalar() or 0
    rejected_count = rejected_result.scalar() or 0

    counts = {
        'pending': pending_count,
        'approved': approved_count,
        'rejected': rejected_count,
        'all': pending_count + approved_count + rejected_count
    }
    
    result = await db.execute(
        query
        .order_by(desc(ManualPayment.created_at))
        .offset((page - 1) * limit)
        .limit(limit)
    )
    
    items = result.all()
    
    return {
        "items": [
            {
                "id": str(payment.id),
                "user": {
                    "id": str(user.id),
                    "full_name": user.full_name,
                    "email": user.email
                },
                "amount": float(payment.amount),
                "network": payment.network,
                "phone_used": payment.phone_used,
                "transaction_id": payment.transaction_id,
                "proof_note": payment.proof_note,
                "status": payment.status,
                "admin_note": payment.admin_note,
                "created_at": payment.created_at.isoformat(),
                "reviewed_at": payment.reviewed_at.isoformat() if payment.reviewed_at else None
            }
            for payment, user in items
        ],
        "total": total,
        "counts": counts,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }

@admin_router.post("/manual-payments/{payment_id}/approve")
async def approve_manual_payment(
    payment_id: str,
    data: AdminApproveRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(ManualPayment).where(ManualPayment.id == payment_id)
    )
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    if payment.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending payments can be approved")
    
    payment.status = "approved"
    payment.admin_note = data.admin_note or ""
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.now(timezone.utc)
    
    user_result = await db.execute(select(User).where(User.id == payment.user_id))
    user = user_result.scalar_one()
    
    user.balance += payment.amount
    
    transaction = Transaction(
        id=uuid.uuid4(),
        user_id=user.id,
        type="deposit",
        amount=payment.amount,
        balance_before=user.balance - payment.amount,
        balance_after=user.balance,
        currency="USD",
        payment_method="manual_mobile_money",
        payment_reference=str(payment.id),
        status="completed",
        description=f"Manual {payment.network} deposit"
    )
    db.add(transaction)
    
    log = AdminActivityLog(
        id=uuid.uuid4(),
        admin_id=admin.id,
        action="approve_manual_payment",
        target_type="manual_payment",
        target_id=str(payment.id),
        details={
            "user_id": str(user.id),
            "user_email": user.email,
            "amount": float(payment.amount),
            "network": payment.network,
            "admin_note": data.admin_note or ""
        }
    )
    db.add(log)
    
    db.add(payment)
    db.add(user)
    await db.commit()
    
    return {"message": "Approved and balance credited"}

@admin_router.post("/manual-payments/{payment_id}/reject")
async def reject_manual_payment(
    payment_id: str,
    data: AdminRejectRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    if not data.admin_note:
        raise HTTPException(status_code=400, detail="Admin note (reason) is required")
    
    result = await db.execute(
        select(ManualPayment).where(ManualPayment.id == payment_id)
    )
    payment = result.scalar_one_or_none()
    
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    
    if payment.status != "pending":
        raise HTTPException(status_code=400, detail="Only pending payments can be rejected")
    
    payment.status = "rejected"
    payment.admin_note = data.admin_note
    payment.reviewed_by = admin.id
    payment.reviewed_at = datetime.now(timezone.utc)
    
    log = AdminActivityLog(
        id=uuid.uuid4(),
        admin_id=admin.id,
        action="reject_manual_payment",
        target_type="manual_payment",
        target_id=str(payment.id),
        details={
            "amount": float(payment.amount),
            "network": payment.network,
            "reason": data.admin_note
        }
    )
    db.add(log)
    db.add(payment)
    await db.commit()
    
    return {"message": "Rejected"}
