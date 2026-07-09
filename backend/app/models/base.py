import uuid

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


def generate_id() -> str:
    return uuid.uuid4().hex
