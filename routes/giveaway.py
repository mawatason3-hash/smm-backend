from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from database import get_db
from middleware.auth_middleware import get_current_user
from models.user import User
from models.giveaway_submission import GiveawaySubmission
from schemas.giveaway import GiveawaySubmissionRequest
from services.notification_service import send_telegram_message
import uuid

router = APIRouter(prefix="/api/giveaway", tags=["giveaway"])

@router.post("/submit")
async def submit_giveaway(
    data: GiveawaySubmissionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    if data.honeypot:
        raise HTTPException(status_code=400, detail="Invalid submission")

    submission = GiveawaySubmission(
        id=uuid.uuid4(),
        user_id=current_user.id,
        giveaway_type=data.giveaway_type.strip(),
        proof_url=str(data.proof_url),
        details=data.details.strip() if data.details else None,
        status="pending"
    )

    db.add(submission)
    await db.commit()
    await db.refresh(submission)

    message = (
        f"New giveaway submission:\n"
        f"User: {current_user.full_name} <{current_user.email}>\n"
        f"Type: {submission.giveaway_type}\n"
        f"Proof URL: {submission.proof_url}\n"
        f"Details: {submission.details or 'N/A'}"
    )

    try:
        await send_telegram_message(message)
    except Exception:
        pass

    return {
        "id": str(submission.id),
        "message": "Giveaway proof submitted successfully. Admin will review your submission and credit your balance if approved."
    }
