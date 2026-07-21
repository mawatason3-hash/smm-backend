from pydantic import BaseModel
from typing import TypeVar, Generic, List
from math import ceil
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

T = TypeVar("T")

class PaginationParams(BaseModel):
    page: int = 1
    limit: int = 20

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit

class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    limit: int
    pages: int

    @classmethod
    def create(cls, items: List[T], total: int, page: int, limit: int):
        return cls(
            items=items,
            total=total,
            page=page,
            limit=limit,
            pages=ceil(total / limit) if limit > 0 else 0
        )

async def get_next_order_number(db: AsyncSession) -> int:
    result = await db.execute(text("SELECT nextval('order_number_seq')"))
    next_val = result.scalar_one()
    return int(next_val)
