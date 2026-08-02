import httpx
import hmac
import hashlib
import re
from typing import Optional, Dict, Any
from config import settings

# ─── PAYSTACK (Card Payments) ─────────────────────────────────────────────────

PAYSTACK_BASE = "https://api.paystack.co"

async def paystack_initialize_transaction(
    email: str,
    amount_usd: float,
    reference: str,
    callback_url: str,
    metadata: Optional[Dict] = None,
    paystack_currency: Optional[str] = None
) -> Optional[Dict]:
    """Initialize a Paystack transaction. Amount in USD converted to Paystack account currency."""
    paystack_currency = (paystack_currency or "USD").strip().upper()
    amount_local = amount_usd
    exchange_rate = 1.0

    zero_decimal_currencies = {"BIF", "CLP", "DJF", "GNF", "ISK", "JPY", "KMF", "KRW", "PYG", "RWF", "UGX", "VUV", "VND", "XAF", "XOF", "XPF", "TZS"}
    if paystack_currency and paystack_currency in zero_decimal_currencies:
        amount_minor = int(round(amount_local))
    else:
        amount_minor = int(round(amount_local * 100))

    headers = {
        "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "email": email,
        "amount": amount_minor,
        "reference": reference,
        "callback_url": callback_url,
        "channels": ["card"],
        "metadata": metadata or {}
    }
    if paystack_currency:
        payload["currency"] = paystack_currency

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"→ Paystack POST {PAYSTACK_BASE}/transaction/initialize")
            print(f"  Email: {email}, Amount USD: ${amount_usd}, Local: {amount_local} {paystack_currency} (minor units: {amount_minor}), Ref: {reference}")
            
            resp = await client.post(
                f"{PAYSTACK_BASE}/transaction/initialize",
                json=payload,
                headers=headers
            )
            data = resp.json()
            print(f"← Paystack response: status={resp.status_code}")
            print(f"  Body: {data}")
            
            if resp.status_code not in (200, 201):
                error_message = data.get('message') or data
                print(f"✗ Paystack API error {resp.status_code}: {error_message}")
                return {"error": str(error_message), "status_code": resp.status_code}
            
            if data.get("status"):
                result = data.get("data")
                print(f"✓ Paystack transaction initialized: {result.get('reference', 'N/A')}")
                return result
            
            error_message = data.get('message') or data
            print(f"✗ Paystack returned status=false: {error_message}")
            return {"error": str(error_message), "status_code": resp.status_code}
        except Exception as e:
            print(f"✗ Paystack request failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
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

# ─── PAWAPAY Configuration Cache ──────────────────────────────────────────────
_active_config_cache = {"data": None, "fetched_at": None}

async def get_pawapay_active_configuration() -> Dict[str, str]:
    """
    Fetches the list of correspondents and their currencies from PawaPay's
    active configuration API. Cached for 1 hour since this rarely changes.
    Returns: {"MTN_MOMO_RWA": "RWF", "AIRTEL_OAPI_ZMB": "ZMW", ...}
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    if (_active_config_cache["data"] is not None and
        _active_config_cache["fetched_at"] is not None and
        now - _active_config_cache["fetched_at"] < timedelta(hours=1)):
        print(f"✓ Using cached PawaPay configuration (expires in {(timedelta(hours=1) - (now - _active_config_cache['fetched_at'])).seconds // 60} min)")
        return _active_config_cache["data"]

    headers = {"Authorization": f"Bearer {settings.PAWAPAY_API_KEY}"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            print(f"→ Fetching PawaPay active configuration from {PAWAPAY_BASE}/v2/active-conf?operationType=DEPOSIT")
            resp = await client.get(
                f"{PAWAPAY_BASE}/v2/active-conf?operationType=DEPOSIT",
                headers=headers
            )
            
            if resp.status_code not in (200, 201):
                print(f"✗ PawaPay active-conf error {resp.status_code}: {resp.text}")
                return {}

            data = resp.json()
            mapping = {}
            
            for country in data.get("countries", []):
                for provider in country.get("providers", []):
                    provider_code = provider.get("provider")
                    if not provider_code:
                        continue
                    for currency_info in provider.get("currencies", []):
                        currency = currency_info.get("currency")
                        operation_types = currency_info.get("operationTypes", {})
                        if currency and operation_types.get("DEPOSIT") is not None:
                            mapping[provider_code] = currency
                            print(f"  ✓ {provider_code} → {currency}")
                            break
            
            _active_config_cache["data"] = mapping
            _active_config_cache["fetched_at"] = now
            print(f"✓ PawaPay configuration fetched: {len(mapping)} providers")
            return mapping
        except Exception as e:
            print(f"✗ Failed to fetch PawaPay configuration: {type(e).__name__}: {e}")
            return {}

async def get_exchange_rate(from_currency: str, to_currency: str) -> float:
    """
    Fetches real-time exchange rate from exchangerate-api.com.
    Falls back to cached rate if API fails.
    """
    if from_currency == to_currency:
        return 1.0
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            print(f"→ Fetching exchange rate: {from_currency} → {to_currency}")
            resp = await client.get(f"https://api.exchangerate-api.com/v4/latest/{from_currency}")
            
            if resp.status_code == 200:
                data = resp.json()
                rate = data["rates"].get(to_currency)
                if rate:
                    print(f"  1 {from_currency} = {rate} {to_currency}")
                    return float(rate)
        except Exception as e:
            print(f"✗ Exchange rate API error: {type(e).__name__}: {e}")
    
    # Fallback rates if API unavailable (will be overridden on retry)
    fallback_rates = {
        ("USD", "RWF"): 1325.0,
        ("USD", "UGX"): 3750.0,
        ("USD", "TZS"): 2550.0,
        ("USD", "GHS"): 14.2,
        ("USD", "LRD"): 60.0,
        ("USD", "ZMW"): 25.5,
        ("USD", "MZN"): 63.5,
        ("USD", "XAF"): 615.0,
        ("USD", "XOF"): 615.0,
        ("USD", "SEN"): 615.0,
    }
    fallback = fallback_rates.get((from_currency, to_currency), 1.0)
    print(f"⚠ Using fallback rate for {from_currency}→{to_currency}: {fallback}")
    return fallback

# ─── PAWAPAY Mobile Money Currency Defaults (Fallback) ──────────────────────
# This is only used as fallback if PawaPay API fetch fails
CORRESPONDENT_CURRENCY_MAP = {
    "MTN_MOMO_RWA": "RWF",
    "AIRTEL_OAPI_RWA": "RWF",
    "MTN_MOMO_UGA": "UGX",
    "AIRTEL_OAPI_UGA": "UGX",
    "VODACOM_TZA": "TZS",
    "AIRTEL_OAPI_TZA": "TZS",
    "MTN_MOMO_GHA": "GHS",
    "VODAFONE_GHA": "GHS",
    "LONESTAR_LBR": "LRD",
    "ORANGE_LBR": "LRD",
    "MTN_MOMO_ZMB": "ZMW",
    "AIRTEL_OAPI_ZMB": "ZMW",
    "VODACOM_MOZ": "MZN",
    "AIRTEL_OAPI_MOZ": "MZN",
    "MTN_MOMO_CMR": "XAF",
    "ORANGE_CMR": "XAF",
    "MTN_MOMO_CIV": "XOF",
    "ORANGE_CIV": "XOF",
    "ORANGE_SEN": "XOF",
    "FREE_SEN": "XOF",
}

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
        "payer": {
            "type": "MMO",
            "accountDetails": {
                "phoneNumber": phone_number,
                "provider": correspondent
            }
        },
        "customerMessage": description
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            print(f"→ PawaPay request: POST {PAWAPAY_BASE}/deposits")
            print(f"  Correspondent: {correspondent}, Phone: {phone_number}, Amount: {amount} {currency}")
            
            resp = await client.post(
                f"{PAWAPAY_BASE}/v2/deposits",
                json=payload,
                headers=headers
            )
            result = resp.json()
            print(f"← PawaPay response: status={resp.status_code}")
            print(f"  Body: {result}")

            if resp.status_code not in (200, 201, 202):
                print(f"✗ PawaPay API error {resp.status_code}: {result.get('message') or result.get('detail') or result}")
                return None

            if isinstance(result, dict) and isinstance(result.get("data"), dict):
                data = result["data"]
                nested_status = data.get("status")
                nested_deposit_id = data.get("depositId") or data.get("id")
                if nested_status in ("REJECTED", "FAILED", "DUPLICATE_IGNORED"):
                    print(f"✗ PawaPay deposit rejected: {nested_status}")
                    return None
                if nested_deposit_id:
                    print(f"✓ PawaPay deposit accepted: {nested_deposit_id}")
                    return result

            if isinstance(result, dict):
                top_status = result.get("status")
                if top_status in ("REJECTED", "FAILED", "DUPLICATE_IGNORED"):
                    print(f"✗ PawaPay deposit rejected: {top_status}")
                    return None

            print(f"✓ PawaPay deposit response received")
            return result
        except Exception as e:
            print(f"✗ PawaPay request failed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
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



