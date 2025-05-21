# src/app/models/post_model.py
from sqlalchemy import Column, Integer, String, Text, DateTime, Boolean, func
from sqlalchemy.orm import relationship
from src.app.database.database import Base
from src.app.models.post_tag_model import post_tag

class Post(Base):
    __tablename__ = "posts"

    id         = Column(Integer, primary_key=True, index=True)
    title      = Column(String,  nullable=False, index=True)
    content    = Column(Text,    nullable=False)
    image_url  = Column(String,  nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    is_archived = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    tags = relationship(
        "Tag",
        secondary=post_tag,
        back_populates="posts",
        lazy="joined",
    )