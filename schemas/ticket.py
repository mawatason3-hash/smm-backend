from pydantic import BaseModel, field_validator
from typing import Optional

class TicketCreateRequest(BaseModel):
    order_id: str
    issue_type: str
    description: str
    attachment_url: Optional[str] = None

    @field_validator('description')
    @classmethod
    def validate_description(cls, v: str) -> str:
        if not v or len(v.strip()) < 10:
            raise ValueError('Description must be at least 10 characters')
        return v.strip()

    @field_validator('issue_type')
    @classmethod
    def validate_issue_type(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError('Issue type is required')
        return v.strip()

class TicketResponse(BaseModel):
    id: str
    order_id: str
    issue_type: str
    description: str
    attachment_url: Optional[str]
    status: str
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class TicketAdminResponse(TicketResponse):
    user_id: str
    user_email: str
    user_name: str
    order_number: int
    service_name: str
    platform: str

class TicketUpdateRequest(BaseModel):
    status: Optional[str] = None
    admin_comment: Optional[str] = None

    @field_validator('status')
    @classmethod
    def validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        value = v.strip().lower()
        if value not in {'open', 'in_review', 'resolved', 'rejected'}:
            raise ValueError('Invalid ticket status')
        return value
