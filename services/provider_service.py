import httpx
from typing import Optional, List, Dict, Any
from config import settings

PROVIDERS = {
    "jap": {
        "url": settings.JAP_API_URL,
        "key": settings.JAP_API_KEY,
    },
    "peakerr": {
        "url": settings.PEAKERR_API_URL,
        "key": settings.PEAKERR_API_KEY,
    },
    "smmwiz": {
        "url": settings.SMMWIZ_API_URL,
        "key": settings.SMMWIZ_API_KEY,
    }
}

async def call_provider_api(provider: str, params: Dict[str, Any]) -> Optional[Dict]:
    config = PROVIDERS.get(provider)
    if not config or not config["key"]:
        return None

    params["key"] = config["key"]

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(config["url"], data=params)
            return response.json()
        except Exception as e:
            print(f"Provider {provider} error: {e}")
            return None

async def get_provider_services(provider: str = "jap") -> List[Dict]:
    result = await call_provider_api(provider, {"action": "services"})
    if not result:
        return []
    if isinstance(result, dict):
        if isinstance(result.get("data"), list):
            return result["data"]
        if isinstance(result.get("services"), list):
            return result["services"]
    return result if isinstance(result, list) else []

async def place_provider_order(
    provider: str,
    service_id: str,
    link: str,
    quantity: int
) -> Optional[Dict]:
    return await call_provider_api(provider, {
        "action": "add",
        "service": service_id,
        "link": link,
        "quantity": quantity
    })

async def check_provider_order_status(provider: str, order_id: str) -> Optional[Dict]:
    return await call_provider_api(provider, {
        "action": "status",
        "order": order_id
    })

async def check_provider_balance(provider: str) -> Optional[Dict]:
    return await call_provider_api(provider, {"action": "balance"})

async def request_provider_refill(provider: str, order_id: str) -> Optional[Dict]:
    return await call_provider_api(provider, {
        "action": "refill",
        "order": order_id
    })

async def cancel_provider_order(provider: str, order_id: str) -> Optional[Dict]:
    return await call_provider_api(provider, {
        "action": "cancel",
        "orders": order_id
    })

def map_provider_status(provider_status: str) -> str:
    """Map provider status strings to our internal status"""
    status_map = {
        "Pending": "pending",
        "In progress": "in_progress",
        "Processing": "processing",
        "Completed": "completed",
        "Partial": "partial",
        "Cancelled": "cancelled",
        "Canceled": "cancelled",
    }
    return status_map.get(provider_status, "pending")
