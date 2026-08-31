"""
Custom SQLAlchemy types for the Sahaara Score platform.
"""

import enum

from sqlalchemy import String, TypeDecorator


class StrEnumType(TypeDecorator):
    """
    Stores Python ``str`` enums as their ``.value`` (lowercase string).

    psycopg3's default enum adaptation sends the enum member's ``.name``
    (uppercase, e.g. ``STUDENT``), which doesn't match our Postgres enum
    types that were created with lowercase values (``student``).

    This TypeDecorator forces the ``.value`` to be sent as a plain string,
    sidestepping psycopg3's enum adaptation entirely.

    Usage::

        class Applicant(Base):
            applicant_type: Mapped[ApplicantType | None] = mapped_column(
                StrEnumType(ApplicantType), nullable=True
            )
    """

    impl = String
    cache_ok = True

    def __init__(self, enum_class: type[enum.Enum], length: int = 64):
        super().__init__()
        self.impl = String(length)
        self.enum_class = enum_class

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, enum.Enum):
                return value.value
            return str(value)
        return None

    def process_result_value(self, value, dialect):
        if value is not None:
            try:
                return self.enum_class(value)
            except (ValueError, KeyError):
                return value
        return None
