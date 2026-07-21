from pydantic import BaseModel
from typing import Optional

class InitiatePaymentRequest(BaseModel):
    amount: float
    payment_method: str  # paystack, pawapay
    country: Optional[str] = None
    phone: Optional[str] = None  # For mobile money
    currency: Optional[str] = "USD"

class PaystackInitResponse(BaseModel):
    authorization_url: str
    access_code: str
    reference: str

class PawaPayInitResponse(BaseModel):
    deposit_id: str
    status: str
    created: str

class TransactionResponse(BaseModel):
    id: str
    type: str
    amount: float
    balance_before: Optional[float]
    balance_after: Optional[float]
    payment_method: Optional[str]
    payment_reference: Optional[str]
    payment_country: Optional[str]
    status: str
    description: Optional[str]
    created_at: str

    class Config:
        from_attributes = True

class AdminAdjustBalanceRequest(BaseModel):
    user_id: str
    amount: float  # Positive = add, negative = deduct
    reason: str
