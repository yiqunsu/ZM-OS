"""Create (or reset) the first owner account for FilmOS.

Usage (from the backend container or local venv):
    python scripts/seed_admin.py <email> <password>
"""

import asyncio
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.models import User, UserRole  # noqa: E402


async def seed_admin(email: str, password: str) -> None:
    async with async_session() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            db.add(User(email=email, password_hash=hash_password(password), role=UserRole.OWNER))
            print(f"created owner account: {email}")
        else:
            user.password_hash = hash_password(password)
            print(f"reset password for existing account: {email}")
        await db.commit()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: python scripts/seed_admin.py <email> <password>")
        sys.exit(1)
    asyncio.run(seed_admin(sys.argv[1], sys.argv[2]))
