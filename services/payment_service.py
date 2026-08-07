import httpx
import hmac
import hashlib
import re
import unicodedata
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

    if paystack_currency != "USD":
        exchange_rate = await get_exchange_rate("USD", paystack_currency)
        if paystack_currency in ("RWF", "UGX", "TZS", "XAF", "XOF"):
            amount_local = int(round(amount_usd * exchange_rate))
        else:
            amount_local = round(amount_usd * exchange_rate, 2)

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
_active_config_cache = {
    "currency_map": None,
    "country_map": None,
    "fetched_at": None,
}


def _normalize_country_name(name: str) -> str:
    if not name:
        return ""
    normalized = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
    return normalized


def _format_pawapay_network_name(provider_code: str) -> str:
    if not provider_code:
        return "Mobile Money"
    code = provider_code.upper()
    if "MTN" in code:
        return "MTN"
    if "AIRTEL" in code:
        return "Airtel"
    if "VODACOM" in code:
        return "Vodacom"
    if "VODAFONE" in code:
        return "Vodafone"
    if "ORANGE" in code:
        return "Orange"
    if "LONESTAR" in code:
        return "Lonestar"
    if "FREE" in code:
        return "Free"
    if "MOOV" in code:
        return "Moov"
    if "WAVE" in code:
        return "Wave"
    return provider_code.replace("_", " ").title()


def _normalize_correspondent_code(code: str) -> str:
    if not code:
        return ""
    return str(code).strip().upper()


async def get_pawapay_active_configuration() -> Dict[str, str]:
    """
    Fetches the list of correspondents and their currencies from PawaPay's
    active configuration API. Cached for 1 hour since this rarely changes.
    Returns: {"MTN_MOMO_RWA": "RWF", "AIRTEL_OAPI_ZMB": "ZMW", ...}
    """
    from datetime import datetime, timezone, timedelta

    now = datetime.now(timezone.utc)
    if (_active_config_cache["currency_map"] is not None and
        _active_config_cache["fetched_at"] is not None and
        now - _active_config_cache["fetched_at"] < timedelta(hours=1)):
        print(f"✓ Using cached PawaPay configuration (expires in {(timedelta(hours=1) - (now - _active_config_cache['fetched_at'])).seconds // 60} min)")
        return _active_config_cache["currency_map"]

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
            country_map: Dict[str, Dict[str, str]] = {}

            for country in data.get("countries", []):
                raw_country_name = country.get("name") or country.get("country") or country.get("countryName") or country.get("displayName")
                if not raw_country_name:
                    continue
                country_name = _normalize_country_name(raw_country_name)
                provider_map: Dict[str, str] = {}

                for provider in country.get("providers", []) or []:
                    provider_code = provider.get("provider") or provider.get("code")
                    provider_code = _normalize_correspondent_code(provider_code)
                    if not provider_code:
                        continue

                    local_currency = None
                    for currency_info in provider.get("currencies", []) or []:
                        currency = currency_info.get("currency")
                        operation_types = currency_info.get("operationTypes") or {}
                        deposit_allowed = False
                        if isinstance(operation_types, dict):
                            deposit_allowed = operation_types.get("DEPOSIT") is not None
                        elif isinstance(operation_types, (list, tuple, set)):
                            deposit_allowed = "DEPOSIT" in operation_types

                        if currency and deposit_allowed:
                            local_currency = currency
                            break

                    if not local_currency:
                        continue

                    mapping[provider_code] = local_currency
                    provider_name = provider.get("name") or provider.get("title") or _format_pawapay_network_name(provider_code)
                    provider_map[provider_name] = provider_code
                    print(f"  ✓ {provider_code} → {local_currency} ({provider_name} in {raw_country_name})")

                if provider_map:
                    country_map[country_name] = provider_map

            _active_config_cache["currency_map"] = mapping
            _active_config_cache["country_map"] = country_map
            _active_config_cache["fetched_at"] = now
            print(f"✓ PawaPay configuration fetched: {len(mapping)} providers across {len(country_map)} countries")
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
    "Algeria": "213",
    "Angola": "244",
    "Benin": "229",
    "Botswana": "267",
    "Burkina Faso": "226",
    "Burundi": "257",
    "Cameroon": "237",
    "Cape Verde": "238",
    "Côte d'Ivoire": "225",
    "Ivory Coast": "225",
    "Eswatini": "268",
    "Ethiopia": "251",
    "Gabon": "241",
    "Gambia": "220",
    "Ghana": "233",
    "Guinea": "224",
    "Guinea-Bissau": "245",
    "Kenya": "254",
    "Lesotho": "266",
    "Liberia": "231",
    "Libya": "218",
    "Madagascar": "261",
    "Malawi": "265",
    "Mali": "223",
    "Mauritania": "222",
    "Mauritius": "230",
    "Morocco": "212",
    "Mozambique": "258",
    "Namibia": "264",
    "Niger": "227",
    "Nigeria": "234",
    "Rwanda": "250",
    "Sao Tome and Principe": "239",
    "Senegal": "221",
    "Seychelles": "248",
    "Sierra Leone": "232",
    "Somalia": "252",
    "South Africa": "27",
    "South Sudan": "211",
    "Sudan": "249",
    "Tanzania": "255",
    "Togo": "228",
    "Tunisia": "216",
    "Uganda": "256",
    "Zambia": "260",
    "Zimbabwe": "263",
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
        cleaned = cleaned.lstrip("0")
        dial_code = COUNTRY_DIAL_CODES.get(user_country or "")
        if dial_code:
            return dial_code + cleaned
        if len(cleaned) >= 8:
            return cleaned

    if len(cleaned) >= 8:
        return cleaned

    raise ValueError(
        "Cannot determine phone normalization for the provided number. "
        "Enter a valid mobile money number for your country."
    )

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

def _normalize_country_key(name: str) -> str:
    return _normalize_country_name(name)


async def get_pawapay_local_currency(correspondent: str) -> Optional[str]:
    correspondent = _normalize_correspondent_code(correspondent)
    if not correspondent:
        return None

    active_config = await get_pawapay_active_configuration()
    if active_config:
        currency = active_config.get(correspondent)
        if currency:
            return currency
    return CORRESPONDENT_CURRENCY_MAP.get(correspondent)


async def get_pawapay_country_correspondents(country: str) -> Dict[str, str]:
    """Return available PawaPay correspondents for the requested country."""
    if not country:
        return {}

    await get_pawapay_active_configuration()
    normalized_country = _normalize_country_key(country)
    country_map = _active_config_cache.get("country_map") or {}

    if normalized_country in country_map:
        return country_map[normalized_country]

    for key, providers in country_map.items():
        normalized_key = _normalize_country_key(key)
        if normalized_country == normalized_key or normalized_country in normalized_key or normalized_key in normalized_country:
            return providers

    for key, providers in COUNTRY_CORRESPONDENT_MAP.items():
        normalized_key = _normalize_country_key(key)
        if normalized_country == normalized_key or normalized_country in normalized_key or normalized_key in normalized_country:
            return providers

    return {}



