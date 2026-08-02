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
    get_pawapay_country_correspondents,
    COUNTRY_CORRESPONDENT_MAP,
    normalize_phone_e164,
    get_pawapay_active_configuration,
    get_exchange_rate,
    CORRESPONDENT_CURRENCY_MAP,
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
    if settings.PAWAPAY_API_KEY and current_user.country:
        correspondents = await get_pawapay_country_correspondents(current_user.country)
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

    paystack_currency = settings.PAYSTACK_CURRENCY.strip().upper() if settings.PAYSTACK_CURRENCY else "KES"
    if paystack_currency != "USD":
        exchange_rate = await get_exchange_rate("USD", paystack_currency)
        if paystack_currency in ("RWF", "UGX", "TZS", "XAF", "XOF"):
            amount_local = int(round(data.amount * exchange_rate))
        else:
            amount_local = round(data.amount * exchange_rate, 2)
    else:
        exchange_rate = 1.0
        amount_local = data.amount

    result = await paystack_initialize_transaction(
        email=current_user.email,
        amount_usd=data.amount,
        reference=reference,
        callback_url=callback_url,
        metadata={"user_id": str(current_user.id), "amount_usd": data.amount},
        paystack_currency=paystack_currency
    )

    if isinstance(result, dict) and result.get("error"):
        error_message = str(result.get("error"))
        if "currency not supported" in error_message.lower():
            print(f"⚠ Paystack currency {paystack_currency} unsupported, retrying without currency field")
            paystack_currency = ""
            exchange_rate = 1.0
            amount_local = data.amount
            result = await paystack_initialize_transaction(
                email=current_user.email,
                amount_usd=data.amount,
                reference=reference,
                callback_url=callback_url,
                metadata={"user_id": str(current_user.id), "amount_usd": data.amount},
                paystack_currency=paystack_currency
            )

    if not result or (isinstance(result, dict) and result.get("error")):
        error_message = result.get("error") if isinstance(result, dict) else "Could not initialize payment. Please try again."
        print(f"✗ Paystack initialize failed: {error_message}")
        raise HTTPException(status_code=400, detail=f"Paystack initialization failed: {error_message}")
    
    print(f"✓ Paystack authorization_url: {result.get('authorization_url', 'N/A')[:50]}...")

    # Create pending transaction
    currency_local = paystack_currency or ""
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
        description=(
            f"Wallet deposit via Paystack - ${data.amount} USD ({amount_local} {currency_local})"
            if paystack_currency and paystack_currency != "USD"
            else f"Wallet deposit via Paystack - ${data.amount} in Paystack account currency"
        ),
        metadata_={
            "paystack_currency": paystack_currency,
            "amount_usd": data.amount,
            "amount_local": amount_local,
            "currency_local": currency_local,
            "exchange_rate": exchange_rate,
        }
    )
    db.add(transaction)
    await db.commit()

    currency_local = paystack_currency or ""
    response_payload = {
        "authorization_url": result["authorization_url"],
        "access_code": result["access_code"],
        "reference": reference,
        "amount_usd": data.amount,
        "currency_local": currency_local,
        "amount_local": amount_local,
        "exchange_rate": exchange_rate,
        "display_text": (
            f"You will be charged ${data.amount} USD (converted to {amount_local} {currency_local})"
            if paystack_currency != "USD"
            else f"You will be charged ${data.amount} USD"
        ),
    }

    return response_payload

@router.post("/paystack/preview")
async def preview_paystack_conversion(
    data: InitiatePaymentRequest,
    current_user: User = Depends(get_current_user)
):
    if data.amount < 1:
        raise HTTPException(status_code=400, detail="Minimum deposit is $1")

    if data.payment_method and data.payment_method != "paystack":
        raise HTTPException(status_code=400, detail="Invalid payment method")

    paystack_currency = settings.PAYSTACK_CURRENCY.strip().upper() if settings.PAYSTACK_CURRENCY else "KES"
    if paystack_currency != "USD":
        exchange_rate = await get_exchange_rate("USD", paystack_currency)
        if paystack_currency in ("RWF", "UGX", "TZS", "XAF", "XOF"):
            amount_local = int(round(data.amount * exchange_rate))
        else:
            amount_local = round(data.amount * exchange_rate, 2)
    else:
        exchange_rate = 1.0
        amount_local = data.amount

    currency_local = paystack_currency
    display_text = (
        f"You will be charged ${data.amount} USD (converted to {amount_local} {currency_local})"
        if paystack_currency != "USD"
        else f"You will be charged ${data.amount} USD"
    )

    return {
        "amount_usd": data.amount,
        "amount_local": amount_local,
        "currency_local": currency_local,
        "exchange_rate": exchange_rate,
        "display_text": display_text,
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
    
    # ──────────── CURRENCY CONVERSION ────────────────────────────────────────
    # Fetch PawaPay's active configuration to get the real currency for this correspondent
    active_config = await get_pawapay_active_configuration()
    local_currency = active_config.get(correspondent)

    if not local_currency:
        if active_config:
            print(f"✗ Correspondent {correspondent} not found in active configuration")
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Mobile money provider {correspondent} is not currently configured on our payment account. "
                    f"Please try a different payment method."
                )
            )
        local_currency = CORRESPONDENT_CURRENCY_MAP.get(correspondent)
        if local_currency:
            print(f"⚠ Using fallback currency for {correspondent}: {local_currency}")

    if not local_currency:
        print(f"✗ Correspondent {correspondent} currency unavailable")
        raise HTTPException(
            status_code=503,
            detail=(
                f"Payment provider {correspondent} is not currently active. "
                f"Please try another payment method."
            )
        )
    
    print(f"✓ Correspondent {correspondent} currency: {local_currency}")
    
    # Convert USD to local currency if needed
    if local_currency != "USD":
        exchange_rate = await get_exchange_rate("USD", local_currency)
        # For currencies without decimal (RWF, UGX, TZS, XAF, XOF), round to 0 decimals
        if local_currency in ("RWF", "UGX", "TZS", "XAF", "XOF"):
            local_amount = int(round(data.amount * exchange_rate))
        else:
            local_amount = round(data.amount * exchange_rate, 2)
        print(f"✓ Converted ${data.amount} USD → {local_amount} {local_currency} (rate: {exchange_rate})")
    else:
        exchange_rate = 1.0
        local_amount = data.amount
        print(f"✓ Using USD directly: {local_amount}")
    
    # ──────────── END CURRENCY CONVERSION ────────────────────────────────────
    
    deposit_id = str(uuid.uuid4())

    result = await pawapay_initiate_deposit(
        deposit_id=deposit_id,
        amount=local_amount,
        currency=local_currency,
        correspondent=correspondent,
        phone_number=normalized_phone,
        description="BOASTLIB TOPUP"
    )
    print(f"✓ PawaPay initiate result for user {current_user.id}: {result}")

    if not result:
        print(f"✗ PawaPay returned None or empty result")
        raise HTTPException(
            status_code=503, 
            detail=f"Mobile money service not available for {current_user.country} {correspondent} at this time. Please try another payment method."
        )

    # Create pending transaction
    # Store both USD (authoritative) and local currency for auditing
    transaction = Transaction(
        user_id=current_user.id,
        type="deposit",
        amount=data.amount,  # USD — this is what gets credited to account
        balance_before=float(current_user.balance),
        balance_after=float(current_user.balance),
        payment_method=f"pawapay_{correspondent}",
        payment_reference=deposit_id,
        payment_country=current_user.country,
        status="pending",
        description=f"Mobile money deposit - ${data.amount} USD ({local_amount} {local_currency})"
    )
    db.add(transaction)
    await db.commit()

    return {
        "deposit_id": deposit_id,
        "status": result.get("status", "PENDING"),
        "amount_usd": data.amount,
        "amount_local": local_amount,
        "currency_local": local_currency,
        "exchange_rate": exchange_rate,
        "message": "Check your phone for the payment prompt"
    }

@router.post("/pawapay/preview")
async def preview_pawapay_conversion(
    data: InitiatePaymentRequest,
    current_user: User = Depends(get_current_user)
):
    """Preview the local currency amount before confirming payment"""
    if not data.payment_method or not data.payment_method.startswith("pawapay_"):
        raise HTTPException(status_code=400, detail="Invalid payment method")
    
    if not current_user.country:
        raise HTTPException(status_code=400, detail="Country not set")
    
    correspondent = data.payment_method.replace("pawapay_", "")
    
    # Get currency for this correspondent
    active_config = await get_pawapay_active_configuration()
    local_currency = active_config.get(correspondent)
    if not local_currency:
        if active_config:
            raise HTTPException(status_code=400, detail=f"Correspondent {correspondent} not found")
        local_currency = CORRESPONDENT_CURRENCY_MAP.get(correspondent)
        if local_currency:
            print(f"⚠ Using fallback currency for preview of {correspondent}: {local_currency}")

    if not local_currency:
        raise HTTPException(status_code=400, detail=f"Correspondent {correspondent} not found")
    
    # Get exchange rate
    if local_currency != "USD":
        exchange_rate = await get_exchange_rate("USD", local_currency)
        if local_currency in ("RWF", "UGX", "TZS", "XAF", "XOF"):
            local_amount = int(round(data.amount * exchange_rate))
        else:
            local_amount = round(data.amount * exchange_rate, 2)
    else:
        exchange_rate = 1.0
        local_amount = data.amount
    
    return {
        "amount_usd": data.amount,
        "amount_local": local_amount,
        "currency_local": local_currency,
        "exchange_rate": exchange_rate,
        "display_text": f"You will be charged approximately {local_amount} {local_currency}"
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
