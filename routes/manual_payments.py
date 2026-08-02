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
from typing import Optional
from datetime import datetime, timezone
from decimal import Decimal
import uuid
from services.notification_service import send_telegram_message

router = APIRouter(prefix="/api/payments", tags=["payments"])

class ManualPaymentRequest(BaseModel):
    amount: float
    network: Optional[str] = None
    phone_used: Optional[str] = None
    transaction_id: Optional[str] = None
    proof_note: Optional[str] = None

class AdminApproveRequest(BaseModel):
    admin_note: Optional[str] = None

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
    
    if current_user.country == "Liberia":
        if not data.network or not data.network.strip():
            raise HTTPException(status_code=400, detail="Network is required")
        if not data.phone_used:
            raise HTTPException(status_code=400, detail="Phone number required")
    else:
        if not data.phone_used:
            raise HTTPException(status_code=400, detail="Contact phone number required for manual payment request")

    payment = ManualPayment(
        id=uuid.uuid4(),
        user_id=current_user.id,
        amount=Decimal(str(data.amount)),
        currency="USD",
        network=data.network or "OTHER",
        phone_used=data.phone_used or "",
        transaction_id=data.transaction_id or "",
        proof_note=data.proof_note or "",
        status="pending"
    )
    
    db.add(payment)
    await db.commit()
    await db.refresh(payment)

    # Try to notify admin via Telegram if configured
    try:
        message = (
            f"New manual payment request:\n"
            f"User: {current_user.full_name} <{current_user.email}>\n"
            f"Country: {current_user.country}\n"
            f"Amount: ${payment.amount}\n"
            f"Phone: {payment.phone_used}\n"
            f"Network: {payment.network}"
        )
        await send_telegram_message(message)
    except Exception:
        pass

    return {
        "id": str(payment.id),
        "message": (
            "Submitted! Admin will credit within 4-10 minutes"
            if current_user.country == "Liberia"
            else "Submitted! Admin will review your request and send country-specific payment instructions. You can also message us on WhatsApp or Telegram to speed things up."
        )
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
async def get_manual_payment_settings(
    country: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(SiteSettings))
    settings = result.scalar_one_or_none()
    is_liberia = (country or "").strip().lower() == "liberia"
    
    if not settings:
        if is_liberia:
            return {
                "mtn_number": "0555166954",
                "orange_number": "",
                "whatsapp": "+250792405593",
                "telegram": "https://t.me/boastlib_support",
                "instructions": "Send the amount to the number above and submit your proof. Transaction ID is optional — you can also message our admin on WhatsApp/Telegram for help.",
                "processing_time": "15-30 mins"
            }
        return {
            "mtn_number": "",
            "orange_number": "",
            "whatsapp": "+250792405593",
            "telegram": "https://t.me/boastlib_support",
            "instructions": "Submit your amount and phone number. Our admin will review and send the correct payment method for your country; you can also message us on WhatsApp/Telegram for faster help.",
            "processing_time": "15-30 mins"
        }
    
    if is_liberia:
        return {
            "mtn_number": settings.liberia_mtn_number,
            "orange_number": settings.liberia_orange_number,
            "whatsapp": settings.whatsapp_support,
            "telegram": settings.telegram_support,
            "instructions": (settings.manual_payment_instructions or "Send the amount to the number above and submit your proof. Transaction ID is optional — you can also message our admin on WhatsApp/Telegram for help."),
            "processing_time": settings.manual_payment_time
        }
    return {
        "mtn_number": "",
        "orange_number": "",
        "whatsapp": settings.whatsapp_support,
        "telegram": settings.telegram_support,
        "instructions": (settings.manual_payment_instructions or "Submit your amount and phone number. Our admin will review and send the correct payment method for your country; you can also message us on WhatsApp/Telegram for faster help."),
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
                    "email": user.email,
                    "country": user.country
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

@admin_router.post("/manual-payments/{payment_id}/notify")
async def notify_manual_payment(
    payment_id: str,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(ManualPayment).where(ManualPayment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")

    user_result = await db.execute(select(User).where(User.id == payment.user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    message = (
        f"Manual payment request reminder:\n"
        f"User: {user.full_name} <{user.email}>\n"
        f"Country: {user.country}\n"
        f"Amount: ${payment.amount}\n"
        f"Phone: {payment.phone_used}\n"
        f"Network: {payment.network}\n"
        f"Status: {payment.status}"
    )
    success = await send_telegram_message(message)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send notification. Check Telegram settings.")

    return {"message": "Notification sent to admin Telegram."}

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
