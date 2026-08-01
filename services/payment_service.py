import httpx
import hmac
import hashlib
import re
from typing import Optional, Dict, Any
from config import settings
from dodopayments import AsyncDodoPayments, DodoPayments

# ─── PAYSTACK (Card Payments) ─────────────────────────────────────────────────

PAYSTACK_BASE = "https://api.paystack.co"

async def paystack_initialize_transaction(
    email: str,
    amount_usd: float,
    reference: str,
    callback_url: str,
    metadata: Optional[Dict] = None
) -> Optional[Dict]:
    """Initialize a Paystack transaction. Amount in USD converted to kobo (×100 NGN)"""
    # Paystack uses NGN by default; for USD we use amount in cents
    amount_cents = int(amount_usd * 100)

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "amount": amount_cents,
        "currency": "USD",
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata or {}
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{PAYSTACK_BASE}/transaction/initialize",
                json=payload,
                headers=headers
            )
            data = resp.json()
            if data.get("status"):
                return data["data"]
            return None
        except Exception as e:
            print(f"Paystack init error: {e}")
            return None

async def paystack_verify_transaction(reference: str) -> Optional[Dict]:
    headers = {"Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                f"{PAYSTACK_BASE}/transaction/verify/{reference}",
                headers=headers
            )
            data = resp.json()
            if data.get("status") and data["data"]["status"] == "success":
                return data["data"]
            return None
        except Exception as e:
            print(f"Paystack verify error: {e}")
            return None

def verify_paystack_webhook(payload: bytes, signature: str) -> bool:
    expected = hmac.new(
        settings.PAYSTACK_SECRET_KEY.encode(),
        payload,
        hashlib.sha512
    ).hexdigest()
    return hmac.compare_digest(expected, signature)

# ─── PAWAPAY (Mobile Money) ───────────────────────────────────────────────────

PAWAPAY_BASE = settings.PAWAPAY_BASE_URL

# Mobile money country → correspondent mapping
COUNTRY_CORRESPONDENT_MAP = {
    "Rwanda": {"MTN": "MTN_MOMO_RWA", "Airtel": "AIRTEL_OAPI_RWA"},
    "Uganda": {"MTN": "MTN_MOMO_UGA", "Airtel": "AIRTEL_OAPI_UGA"},
    "Tanzania": {"Vodacom": "VODACOM_TZA", "Airtel": "AIRTEL_OAPI_TZA"},
    "Ghana": {"MTN": "MTN_MOMO_GHA", "Vodafone": "VODAFONE_GHA"},
    "Liberia": {"Lonestar": "LONESTAR_LBR", "Orange": "ORANGE_LBR"},
    "Zambia": {"MTN": "MTN_MOMO_ZMB", "Airtel": "AIRTEL_OAPI_ZMB"},
    "Mozambique": {"Vodacom": "VODACOM_MOZ", "Airtel": "AIRTEL_OAPI_MOZ"},
    "Cameroon": {"MTN": "MTN_MOMO_CMR", "Orange": "ORANGE_CMR"},
    "Ivory Coast": {"MTN": "MTN_MOMO_CIV", "Orange": "ORANGE_CIV"},
    "Côte d'Ivoire": {"MTN": "MTN_MOMO_CIV", "Orange": "ORANGE_CIV"},
    "Senegal": {"Orange": "ORANGE_SEN", "Free": "FREE_SEN"},
}

COUNTRY_DIAL_CODES = {
    "Rwanda": "250",
    "Liberia": "231",
    "Kenya": "254",
    "Uganda": "256",
    "Tanzania": "255",
    "Nigeria": "234",
    "Ghana": "233",
    "Zambia": "260",
    "Mozambique": "258",
    "Cameroon": "237",
    "Ivory Coast": "225",
    "Côte d'Ivoire": "225",
    "Senegal": "221",
}


def normalize_phone_e164(raw_phone: str, user_country: str = None) -> str:
    """
    Accepts phone numbers in common formats and returns a normalized E.164-like
    number for PawaPay (digits only, no leading + or 0).
    """
    if not raw_phone or not str(raw_phone).strip():
        raise ValueError("Phone number required for mobile money")

    cleaned = re.sub(r"\D", "", str(raw_phone).strip())
    if not cleaned:
        raise ValueError("Phone number required for mobile money")

    # If the caller already sent an international format, keep it.
    for dial_code in COUNTRY_DIAL_CODES.values():
        if cleaned.startswith(dial_code) and len(cleaned) >= len(dial_code) + 8:
            return cleaned

    # If the caller sent a local national format, prefix the country dial code.
    if cleaned.startswith("0"):
        cleaned = cleaned[1:]
        dial_code = COUNTRY_DIAL_CODES.get(user_country or "")
        if not dial_code:
            raise ValueError(
                f"Cannot determine country code for phone normalization — "
                f"user country '{user_country}' not in COUNTRY_DIAL_CODES"
            )
        return dial_code + cleaned

    return cleaned

async def pawapay_initiate_deposit(
    deposit_id: str,
    amount: float,
    currency: str,
    correspondent: str,
    phone_number: str,
    description: str
) -> Optional[Dict]:
    from datetime import datetime, timezone

    headers = {
        "Authorization": f"Bearer {settings.PAWAPAY_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "depositId": deposit_id,
        "amount": str(amount),
        "currency": currency,
        "correspondent": correspondent,
        "payer": {
            "type": "MSISDN",
            "address": {"value": phone_number}
        },
        "customerTimestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "statementDescription": description
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{PAWAPAY_BASE}/deposits",
                json=payload,
                headers=headers
            )
            result = resp.json()
            print(f"PawaPay response: status={resp.status_code} body={result}")

            if resp.status_code not in (200, 201, 202):
                print(f"PawaPay rejected deposit: status={resp.status_code}")
                return None

            if result.get("status") in ("REJECTED", "FAILED", "DUPLICATE_IGNORED"):
                print(f"PawaPay deposit not accepted: {result}")
                return None

            return result
        except Exception as e:
            print(f"PawaPay deposit error: {e}")
            return None

async def pawapay_check_deposit(deposit_id: str) -> Optional[Dict]:
    headers = {"Authorization": f"Bearer {settings.PAWAPAY_API_KEY}"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(
                f"{PAWAPAY_BASE}/deposits/{deposit_id}",
                headers=headers
            )
            data = resp.json()
            return data[0] if isinstance(data, list) else data
        except Exception as e:
            print(f"PawaPay check error: {e}")
            return None

def get_country_correspondents(country: str) -> Dict[str, str]:
    return COUNTRY_CORRESPONDENT_MAP.get(country, {})


async def create_dodo_checkout_session(
    amount_usd: float,
    customer_email: str,
    return_url: str,
    metadata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, str]]:
    if not settings.DODO_PAYMENTS_API_KEY or not settings.DODO_PAYMENTS_PRODUCT_ID:
        return None

    async with AsyncDodoPayments(
        bearer_token=settings.DODO_PAYMENTS_API_KEY,
        webhook_key=settings.DODO_PAYMENTS_WEBHOOK_KEY or None,
        environment=settings.DODO_PAYMENTS_ENVIRONMENT or "test_mode",
    ) as client:
        try:
            response = await client.checkout_sessions.create(
                product_cart=[
                    {
                        "product_id": settings.DODO_PAYMENTS_PRODUCT_ID,
                        "quantity": 1,
                        "amount": int(amount_usd * 100),
                    }
                ],
                billing_address={"country": "US"},
                return_url=return_url,
                metadata=metadata or {},
            )
            return {
                "session_id": response.session_id,
                "checkout_url": response.checkout_url,
                "client_secret": response.client_secret,
            }
        except Exception as e:
            print(f"Dodo checkout error: {e}")
            return None


def verify_dodo_webhook(
    payload: bytes,
    headers: Dict[str, str]
) -> Optional[Dict[str, Any]]:
    if not settings.DODO_PAYMENTS_API_KEY or not settings.DODO_PAYMENTS_WEBHOOK_KEY:
        return None

    try:
        with DodoPayments(
            bearer_token=settings.DODO_PAYMENTS_API_KEY,
            webhook_key=settings.DODO_PAYMENTS_WEBHOOK_KEY,
            environment=settings.DODO_PAYMENTS_ENVIRONMENT or "test_mode",
        ) as client:
            event = client.webhooks.unwrap(
                payload.decode("utf-8"),
                headers=headers,
            )
            return event.model_dump() if hasattr(event, "model_dump") else event
    except Exception as e:
        print(f"Dodo webhook verification error: {e}")
        return None
