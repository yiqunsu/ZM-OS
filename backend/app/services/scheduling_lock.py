"""One transaction lock covers the complete scheduling input set, including new rows."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def lock_scheduling_inputs(db: AsyncSession) -> None:
    # Row locks alone cannot fence a concurrent insertion into the pending-order set.
    # All normal business entry points and Agent confirmation share this key.
    await db.execute(text("SELECT pg_advisory_xact_lock(7302, 1)"))
