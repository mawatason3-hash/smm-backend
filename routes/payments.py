from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from database import get_db
from models.user import User
from models.transaction import Transaction
from models.admin_log import AdminActivityLog
from schemas.payment import InitiatePaymentRequest, AdminAdjustBalanceRequest
from middleware.auth_middleware import get_current_user, get_current_admin
from services.payment_service import (
    paystack_initialize_transaction,
    paystack_verify_transaction,
    verify_paystack_webhook,
    pawapay_initiate_deposit,
    pawapay_check_deposit,
    get_country_correspondents,
    COUNTRY_CORRESPONDENT_MAP,
    normalize_phone_e164,
)
from config import settings
from decimal import Decimal
import uuid
import secrets

router = APIRouter(prefix="/api/payments", tags=["payments"])

@router.get("/methods")
async def get_payment_methods(
    current_user: User = Depends(get_current_user)
):
    """Return available payment methods, with mobile money options per country"""
    methods = []

    # Paystack for card payments
    if settings.PAYSTACK_SECRET_KEY:
        methods.append({
            "id": "paystack",
            "name": "Credit/Debit Card",
            "description": "Visa, Mastercard via Paystack",
            "icon": "💳",
            "instant": True,
            "countries": "All"
        })

    # Add mobile money options based on country only when PawaPay is configured
    if settings.PAWAPAY_API_KEY and current_user.country and current_user.country in COUNTRY_CORRESPONDENT_MAP:
        correspondents = COUNTRY_CORRESPONDENT_MAP[current_user.country]
        for network, code in correspondents.items():
            methods.append({
                "id": f"pawapay_{code}",
                "name": f"{network} Mobile Money",
                "description": f"{network} {current_user.country}",
                "icon": "mobile",
                "instant": True,
                "countries": current_user.country,
                "correspondent": code
            })

    methods.append({
        "id": "manual_transfer",
        "name": "Manual Transfer",
        "description": "Use bank/mobile transfer and submit proof for review",
        "icon": "manual",
        "instant": False,
        "countries": "All"
    })

    # Always add crypto option
    methods.append({
        "id": "crypto",
        "name": "Cryptocurrency",
        "description": "Bitcoin, USDT TRC20",
        "icon": "crypto",
        "instant": False,
        "countries": "All"
    })

    return {"methods": methods, "country": current_user.country}

@router.post("/paystack/initialize")
async def initialize_paystack(
    data: InitiatePaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify Paystack is configured
    if not settings.PAYSTACK_SECRET_KEY:
        print(f"✗ Paystack is not configured (PAYSTACK_SECRET_KEY not set)")
        raise HTTPException(status_code=503, detail="Paystack service is not configured")
    
    if data.amount < 1:
        print(f"✗ Amount {data.amount} is below minimum of $1")
        raise HTTPException(status_code=400, detail="Minimum deposit is $1")

    if not current_user.email:
        print(f"✗ User {current_user.id} has no email address")
        raise HTTPException(status_code=400, detail="Your account must have an email address for card payments")

    reference = f"BOAST_{secrets.token_hex(8).upper()}"
    callback_url = f"{settings.FRONTEND_URL}/dashboard/wallet?ref={reference}"
    
    print(f"→ Paystack initialization: email={current_user.email}, amount=${data.amount}, ref={reference}")

    result = await paystack_initialize_transaction(
        email=current_user.email,
        amount_usd=data.amount,
        reference=reference,
        callback_url=callback_url,
        metadata={"user_id": str(current_user.id), "amount": data.amount}
    )

    if not result:
        print(f"✗ Paystack returned empty result")
        raise HTTPException(status_code=400, detail="Could not initialize payment. Please try again.")
    
    print(f"✓ Paystack authorization_url: {result.get('authorization_url', 'N/A')[:50]}...")

    # Create pending transaction
    transaction = Transaction(
        user_id=current_user.id,
        type="deposit",
        amount=data.amount,
        balance_before=float(current_user.balance),
        balance_after=float(current_user.balance),  # Updated on confirmation
        payment_method="paystack",
        payment_reference=reference,
        payment_country=current_user.country,
        status="pending",
        description=f"Wallet deposit via Paystack - ${data.amount}"
    )
    db.add(transaction)
    await db.commit()

    return {
        "authorization_url": result["authorization_url"],
        "access_code": result["access_code"],
        "reference": reference
    }

@router.get("/paystack/verify/{reference}")
async def verify_paystack(
    reference: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Find pending transaction
    result = await db.execute(
        select(Transaction).where(
            Transaction.payment_reference == reference,
            Transaction.user_id == current_user.id,
            Transaction.status == "pending"
        )
    )
    transaction = result.scalar_one_or_none()

    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")

    # Verify with Paystack
    payment_data = await paystack_verify_transaction(reference)

    if not payment_data:
        raise HTTPException(status_code=400, detail="Payment not confirmed")

    # Credit user
    amount = Decimal(str(transaction.amount))
    current_user.balance += amount
    transaction.status = "completed"
    transaction.balance_before = float(current_user.balance - amount)
    transaction.balance_after = float(current_user.balance)

    await db.commit()

    return {
        "status": "success",
        "amount_credited": float(amount),
        "new_balance": float(current_user.balance)
    }

@router.post("/paystack/webhook")
async def paystack_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_paystack_signature: str = Header(None)
):
    body = await request.body()

    if not verify_paystack_webhook(body, x_paystack_signature or ""):
        raise HTTPException(status_code=400, detail="Invalid signature")

    payload = await request.json()

    if payload.get("event") == "charge.success":
        reference = payload["data"]["reference"]

        result = await db.execute(
            select(Transaction).where(
                Transaction.payment_reference == reference,
                Transaction.status == "pending"
            )
        )
        transaction = result.scalar_one_or_none()

        if transaction:
            user_result = await db.execute(select(User).where(User.id == transaction.user_id))
            user = user_result.scalar_one_or_none()

            if user:
                amount = Decimal(str(transaction.amount))
                user.balance += amount
                transaction.status = "completed"
                transaction.balance_after = float(user.balance)
                await db.commit()

    return {"status": "ok"}

@router.post("/pawapay/initiate")
async def initiate_pawapay(
    data: InitiatePaymentRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Verify PawaPay is configured
    if not settings.PAWAPAY_API_KEY:
        print(f"✗ PawaPay is not configured (PAWAPAY_API_KEY not set)")
        raise HTTPException(status_code=503, detail="PawaPay service is not configured")
    
    if not data.phone:
        raise HTTPException(status_code=400, detail="Phone number required for mobile money")

    # Verify user has a country set
    if not current_user.country:
        print(f"✗ User {current_user.id} has no country set")
        raise HTTPException(status_code=400, detail="Your account country must be set for mobile money payments")

    try:
        normalized_phone = normalize_phone_e164(data.phone, current_user.country)
        print(f"✓ Normalized phone: {data.phone} → {normalized_phone} (country: {current_user.country})")
    except ValueError as exc:
        print(f"✗ Phone normalization failed: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Extract correspondent from payment_method (e.g., "pawapay_MTN_MOMO_RWA")
    if not data.payment_method or not data.payment_method.startswith("pawapay_"):
        print(f"✗ Invalid payment method: {data.payment_method}")
        raise HTTPException(status_code=400, detail=f"Invalid payment method: {data.payment_method}")
    
    correspondent = data.payment_method.replace("pawapay_", "")
    print(f"✓ Payment method: {data.payment_method} → correspondent: {correspondent}")
    
    deposit_id = str(uuid.uuid4())

    result = await pawapay_initiate_deposit(
        deposit_id=deposit_id,
        amount=data.amount,
        currency="USD",
        correspondent=correspondent,
        phone_number=normalized_phone,
        description="BOASTLIB TOPUP"
    )
    print(f"✓ PawaPay initiate result for user {current_user.id}: {result}")

    if not result:
        print(f"✗ PawaPay returned None or empty result")
        raise HTTPException(status_code=400, detail="Could not initiate mobile money payment")

    # Create pending transaction
    transaction = Transaction(
        user_id=current_user.id,
        type="deposit",
        amount=data.amount,
        balance_before=float(current_user.balance),
        balance_after=float(current_user.balance),
        payment_method=f"pawapay_{correspondent}",
        payment_reference=deposit_id,
        payment_country=current_user.country,
        status="pending",
        description=f"Mobile money deposit - ${data.amount}"
    )
    db.add(transaction)
    await db.commit()

    return {
        "deposit_id": deposit_id,
        "status": result.get("status", "PENDING"),
        "message": "Check your phone for the payment prompt"
    }

@router.post("/pawapay/webhook")
async def pawapay_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    payload = await request.json()

    deposit_id = payload.get("depositId")
    status = payload.get("status")

    if not deposit_id:
        return {"status": "ok"}

    result = await db.execute(
        select(Transaction).where(
            Transaction.payment_reference == deposit_id,
            Transaction.status == "pending"
        )
    )
    transaction = result.scalar_one_or_none()

    if transaction and status == "COMPLETED":
        user_result = await db.execute(select(User).where(User.id == transaction.user_id))
        user = user_result.scalar_one_or_none()

        if user:
            amount = Decimal(str(transaction.amount))
            user.balance += amount
            transaction.status = "completed"
            transaction.balance_after = float(user.balance)
            await db.commit()

    return {"status": "ok"}

# Admin: adjust user balance
@router.post("/admin/adjust-balance")
async def admin_adjust_balance(
    data: AdminAdjustBalanceRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    user_result = await db.execute(select(User).where(User.id == uuid.UUID(data.user_id)))
    user = user_result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    balance_before = float(user.balance)
    user.balance += Decimal(str(data.amount))

    if user.balance < 0:
        raise HTTPException(status_code=400, detail="Balance cannot go below 0")

    transaction = Transaction(
        user_id=user.id,
        type="admin_adjustment",
        amount=data.amount,
        balance_before=balance_before,
        balance_after=float(user.balance),
        payment_method="admin",
        status="completed",
        description=f"Admin adjustment by {admin.email}: {data.reason}"
    )
    db.add(transaction)

    log = AdminActivityLog(
        admin_id=admin.id,
        action="adjust_balance",
        target_type="user",
        target_id=str(user.id),
        details={
            "amount": float(data.amount),
            "balance_before": balance_before,
            "balance_after": float(user.balance),
            "reason": data.reason,
        }
    )
    db.add(log)
    await db.commit()

    return {
        "message": "Balance adjusted",
        "new_balance": float(user.balance),
        "adjusted_by": data.amount
    }
