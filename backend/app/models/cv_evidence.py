"""Private CV passages, deliberately separate from the shared knowledge base."""
from sqlalchemy import ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector
from app.database import Base


class CVPassage(Base):
    __tablename__ = "cv_passages"
    __table_args__ = (Index("uq_cv_passage_version", "document_id", "encoder", "passage_id", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("cv_documents.id", ondelete="CASCADE"), index=True)
    cv_sha256: Mapped[str] = mapped_column(String(64))
    encoder: Mapped[str] = mapped_column(String(64))
    passage_id: Mapped[str] = mapped_column(String(160))
    source_block_id: Mapped[str] = mapped_column(String(160))
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    locator: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(768).with_variant(JSON(), "sqlite"))
