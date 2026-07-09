from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Pattern


async def list_patterns(db: AsyncSession) -> list[Pattern]:
    result = await db.execute(select(Pattern).order_by(Pattern.name))
    return list(result.scalars().all())
