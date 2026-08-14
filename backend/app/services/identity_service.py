from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, UserRole


class IdentityConflictError(Exception):
    """A verified external identity cannot be mapped to exactly one local user."""


@dataclass(frozen=True)
class ExternalIdentity:
    subject: str
    email: str
    role: UserRole


def _synchronize_projection(user: User, identity: ExternalIdentity) -> None:
    user.email = identity.email
    user.role = identity.role


async def _find_by_subject(db: AsyncSession, subject: str) -> User | None:
    result = await db.execute(select(User).where(User.external_subject == subject))
    return result.scalar_one_or_none()


async def resolve_external_user(db: AsyncSession, identity: ExternalIdentity) -> User:
    """Resolve a Casdoor subject to a stable local user, linking by email once.

    The unique subject/email constraints are the final concurrency guard. If two
    first requests race, the loser re-reads the row created by the winner.
    """

    existing = await _find_by_subject(db, identity.subject)
    if existing is not None:
        _synchronize_projection(existing, identity)
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise IdentityConflictError from exc
        return existing

    email_result = await db.execute(
        select(User)
        .where(func.lower(User.email) == identity.email)
        .with_for_update()
    )
    email_matches = email_result.scalars().all()
    if len(email_matches) > 1:
        raise IdentityConflictError

    if email_matches:
        user = email_matches[0]
        if user.external_subject not in (None, identity.subject):
            raise IdentityConflictError
        user.external_subject = identity.subject
        _synchronize_projection(user, identity)
    else:
        user = User(
            email=identity.email,
            external_subject=identity.subject,
            password_hash=None,
            role=identity.role,
        )
        db.add(user)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        winner = await _find_by_subject(db, identity.subject)
        if winner is None or winner.email.lower() != identity.email:
            raise IdentityConflictError from exc
        _synchronize_projection(winner, identity)
        return winner

    await db.refresh(user)
    return user
