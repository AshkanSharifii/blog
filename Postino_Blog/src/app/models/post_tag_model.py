# post_tag_model.py  (NEW – association table)
from sqlalchemy import Table, Column, Integer, ForeignKey
from src.app.database.database import Base

post_tag = Table(
    "post_tag",
    Base.metadata,
    Column("post_id", Integer, ForeignKey("posts.id", ondelete="CASCADE")),
    Column("tag_id",  Integer, ForeignKey("tags.id",  ondelete="CASCADE")),
)
