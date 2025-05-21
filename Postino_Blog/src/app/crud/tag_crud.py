# tag_crud.py
from typing import List, Sequence
from sqlalchemy.orm import Session
from src.app.models.tag_model import Tag

def get_or_create_tags(db: Session, names: Sequence[str]) -> List[Tag]:
    """Return Tag objects, creating missing ones."""
    tags = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        tag = db.query(Tag).filter(Tag.name == name).first()
        if tag is None:
            tag = Tag(name=name)
            db.add(tag)
            db.flush()          # get id immediately
        tags.append(tag)
    return tags
