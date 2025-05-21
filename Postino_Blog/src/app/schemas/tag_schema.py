# tag_schema.py
from pydantic import BaseModel

class TagBase(BaseModel):
    name: str

class TagOut(TagBase):
    id: int

    class Config:
        from_attributes = True
