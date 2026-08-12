from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from database import get_db
from models.ticket import Ticket
from models.user import User
from models.order import Order
from models.service import Service
from schemas.ticket import TicketCreateRequest, TicketResponse, TicketAdminResponse, TicketUpdateRequest
from middleware.auth_middleware import get_current_user, get_current_admin
import uuid
import os
from services.notification_service import notify_admins, send_email

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), '..', 'uploads')
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.post("", response_model=TicketResponse)
async def create_ticket(
    data: TicketCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Order).where(Order.id == uuid.UUID(data.order_id), Order.user_id == current_user.id))
    order = result.scalar_one_or_none()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    if order.status in {"completed", "cancelled", "refunded"}:
        raise HTTPException(status_code=400, detail="Ticket requests are not available for completed, cancelled, or refunded orders")

    ticket = Ticket(
        order_id=order.id,
        user_id=current_user.id,
        issue_type=data.issue_type,
        description=data.description,
        attachment_url=data.attachment_url,
        status="open"
    )
    db.add(ticket)
    await db.commit()
    await db.refresh(ticket)

    # Notify admins (non-blocking placeholder)
    try:
        await notify_admins(ticket)
    except Exception:
        pass

    return {
        "id": str(ticket.id),
        "order_id": str(ticket.order_id),
        "issue_type": ticket.issue_type,
        "description": ticket.description,
        "attachment_url": ticket.attachment_url,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }

@router.post("/upload")
async def upload_ticket_attachment(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user)
):
    filename = f"ticket-{uuid.uuid4().hex}-{file.filename}"
    file_path = os.path.join(UPLOAD_DIR, filename)
    with open(file_path, "wb") as out_file:
        out_file.write(await file.read())
    return {"url": f"/uploads/{filename}"}

@router.get("/me")
async def list_my_tickets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = 1,
    limit: int = 20
):
    query = select(Ticket, Order).join(Order, Ticket.order_id == Order.id).where(Ticket.user_id == current_user.id)
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(desc(Ticket.created_at)).offset((page - 1) * limit).limit(limit)
    results = (await db.execute(query)).all()

    return {
        "items": [
            {
                "id": str(ticket.id),
                "order_id": str(ticket.order_id),
                "order_number": order.order_number,
                "issue_type": ticket.issue_type,
                "description": ticket.description,
                "attachment_url": ticket.attachment_url,
                "status": ticket.status,
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
            }
            for ticket, order in results
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }

@router.get("/admin")
async def admin_list_tickets(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
    status: str = None,
    page: int = 1,
    limit: int = 20
):
    valid_statuses = {"open", "in_review", "resolved", "rejected"}
    normalized_status = status.strip().lower() if status else None
    if normalized_status and normalized_status not in valid_statuses:
        raise HTTPException(status_code=400, detail="Invalid ticket status filter")

    # Join Service as well so we can include service metadata without extra lazy loads
    query = select(Ticket, User, Order, Service).join(User, Ticket.user_id == User.id).join(Order, Ticket.order_id == Order.id).join(Service, Order.service_id == Service.id)
    if normalized_status:
        query = query.where(Ticket.status == normalized_status)

    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    query = query.order_by(desc(Ticket.updated_at), desc(Ticket.created_at)).offset((page - 1) * limit).limit(limit)
    results = (await db.execute(query)).all()

    return {
        "items": [
            {
                "id": str(ticket.id),
                "order_id": str(ticket.order_id),
                "order_number": order.order_number,
                "service_name": service.name,
                "platform": service.platform,
                "user_id": str(user.id),
                "user_email": user.email,
                "user_name": user.full_name,
                "issue_type": ticket.issue_type,
                "description": ticket.description,
                "attachment_url": ticket.attachment_url,
                "status": ticket.status,
                "admin_comment": ticket.admin_comment or "",
                "created_at": ticket.created_at.isoformat(),
                "updated_at": ticket.updated_at.isoformat(),
            }
            for ticket, user, order, service in results
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "pages": (total + limit - 1) // limit
    }

@router.put("/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    data: TicketUpdateRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Ticket).where(Ticket.id == uuid.UUID(ticket_id)))
    ticket = result.scalar_one_or_none()
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    if data.status is not None:
        ticket.status = data.status
    if data.admin_comment is not None:
        ticket.admin_comment = data.admin_comment
    await db.commit()
    await db.refresh(ticket)

    # Notify the ticket owner via email if available
    try:
        # load user
        u_res = await db.execute(select(User).where(User.id == ticket.user_id))
        user = u_res.scalar_one_or_none()
        if user and user.email:
            subject = f"Update on your ticket #{ticket.id}"
            html = f"<p>Your ticket regarding order {ticket.order_id} has been updated by admin.</p><p>Status: {ticket.status}</p><p>Comment: {ticket.admin_comment or ''}</p>"
            await send_email(user.email, subject, html)
    except Exception:
        pass

    return {
        "id": str(ticket.id),
        "order_id": str(ticket.order_id),
        "issue_type": ticket.issue_type,
        "description": ticket.description,
        "attachment_url": ticket.attachment_url,
        "status": ticket.status,
        "created_at": ticket.created_at.isoformat(),
        "updated_at": ticket.updated_at.isoformat(),
    }
