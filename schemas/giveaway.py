from pydantic import BaseModel, HttpUrl, constr
from typing import Optional

class GiveawaySubmissionRequest(BaseModel):
    giveaway_type: constr(strip_whitespace=True, min_length=1, max_length=100)
    proof_url: HttpUrl
    details: Optional[str] = None
    honeypot: Optional[str] = None

class GiveawaySubmissionResponse(BaseModel):
    id: str
    message: str

class AdminGiveawayApproveRequest(BaseModel):
    amount: float
    admin_note: Optional[str] = None

class AdminGiveawayRejectRequest(BaseModel):
    admin_note: constr(strip_whitespace=True, min_length=1)
