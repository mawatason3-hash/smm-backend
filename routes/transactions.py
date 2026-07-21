from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc
from database import get_db
from models.user import User
from models.transaction import Transaction
from middleware.auth_middleware import get_current_user

router = APIRouter(prefix="/api/transactions", tags=["transactions"])

@router.get("")
async def get_transactions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    type: str = Query(None),
    status: str = Query(None)
):
    query = select(Transaction).where(Transaction.user_id == current_user.id)

    if type:
        query = query.where(Transaction.type == type)
    if status:
        query = query.where(Transaction.status == status)

    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()

    query = query.order_by(desc(Transaction.created_at)).offset((page - 1) * limit).limit(limit)
    results = (await db.execute(query)).scalars().all()

    return {
        "items": [
            {
                "id": str(tx.id),
                "type": tx.type,
                "amount": float(tx.amount),
                "balance_before": float(tx.balance_before) if tx.balance_before is not None else None,
                "balance_after": float(tx.balance_after) if tx.balance_after is not None else None,
                "payment_method": tx.payment_method,
                "payment_reference": tx.payment_reference,
                "payment_country": tx.payment_country,
                "status": tx.status,
                "description": tx.description,
                "created_at": tx.created_at.isoformat(),
            }
            for tx in results
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit
    }
