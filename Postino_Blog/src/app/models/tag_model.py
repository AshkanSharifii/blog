# tag_model.py
from sqlalchemy import Column, Integer, String
from sqlalchemy.orm import relationship
from src.app.database.database import Base
from src.app.models.post_tag_model import post_tag

class Tag(Base):
    __tablename__ = "tags"

    id   = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, nullable=False)

    posts = relationship(
        "Post",
        secondary=post_tag,
        back_populates="tags",
        lazy="joined",
    )
