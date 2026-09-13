import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.shared.mixins import GUID, PrimaryKeyMixin, TimestampMixin


class Note(PrimaryKeyMixin, TimestampMixin, Base):
    """A user-authored note attached to any business entity. Notes feed the
    unified entity timeline."""

    __tablename__ = "notes"

    body: Mapped[str] = mapped_column(Text, nullable=False)
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    entity_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
