# src/app/api/api_v1/endpoints/tags.py
from typing import List, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, asc

from src.app.database.database import get_db
from src.app.models.tag_model import Tag
from src.app.models.post_model import Post
from src.app.models.post_tag_model import post_tag

router = APIRouter()


@router.get("/", response_model=List[str])
def list_all_tags(
        db: Session = Depends(get_db),
        sort_by: str = Query("name", description="Field to sort by (name, post_count)"),
        sort_desc: bool = Query(False, description="Sort in descending order"),
        skip: int = Query(0, description="Number of tags to skip"),
        limit: int = Query(100, description="Maximum number of tags to return"),
        min_posts: int = Query(0, description="Minimum number of posts a tag must have")
):
    """
    List all tags, with optional sorting and filtering.

    - sort_by: Field to sort by (name, post_count)
    - sort_desc: Whether to sort in descending order
    - skip: Number of tags to skip (for pagination)
    - limit: Maximum number of tags to return
    - min_posts: Only show tags with at least this many posts
    """
    if sort_by == "post_count":
        # Count posts per tag and sort by that count
        query = db.query(
            Tag.name,
            func.count(post_tag.c.post_id).label("post_count")
        ).outerjoin(
            post_tag,
            Tag.id == post_tag.c.tag_id
        ).group_by(
            Tag.id
        ).having(
            func.count(post_tag.c.post_id) >= min_posts
        )

        # Apply sorting
        if sort_desc:
            query = query.order_by(desc("post_count"), asc(Tag.name))
        else:
            query = query.order_by(asc("post_count"), asc(Tag.name))

        # Get paginated results
        results = query.offset(skip).limit(limit).all()

        # Extract just the tag names
        return [r[0] for r in results]
    else:
        # Default sort by name
        query = db.query(
            Tag.name,
            func.count(post_tag.c.post_id).label("post_count")
        ).outerjoin(
            post_tag,
            Tag.id == post_tag.c.tag_id
        ).group_by(
            Tag.id
        ).having(
            func.count(post_tag.c.post_id) >= min_posts
        )

        # Apply sorting
        if sort_desc:
            query = query.order_by(desc(Tag.name))
        else:
            query = query.order_by(asc(Tag.name))

        # Get paginated results
        results = query.offset(skip).limit(limit).all()

        # Extract just the tag names
        return [r[0] for r in results]


@router.get("/with-counts", response_model=List[dict])
def list_tags_with_counts(
        db: Session = Depends(get_db),
        sort_by: str = Query("name", description="Field to sort by (name, post_count)"),
        sort_desc: bool = Query(False, description="Sort in descending order"),
        skip: int = Query(0, description="Number of tags to skip"),
        limit: int = Query(100, description="Maximum number of tags to return"),
        min_posts: int = Query(0, description="Minimum number of posts a tag must have")
):
    """
    List all tags with post counts.

    - sort_by: Field to sort by (name, post_count)
    - sort_desc: Whether to sort in descending order
    - skip: Number of tags to skip (for pagination)
    - limit: Maximum number of tags to return
    - min_posts: Only show tags with at least this many posts
    """
    query = db.query(
        Tag.id,
        Tag.name,
        func.count(post_tag.c.post_id).label("post_count")
    ).outerjoin(
        post_tag,
        Tag.id == post_tag.c.tag_id
    ).group_by(
        Tag.id
    ).having(
        func.count(post_tag.c.post_id) >= min_posts
    )

    # Apply sorting
    if sort_by == "post_count":
        if sort_desc:
            query = query.order_by(desc("post_count"), asc(Tag.name))
        else:
            query = query.order_by(asc("post_count"), asc(Tag.name))
    else:
        if sort_desc:
            query = query.order_by(desc(Tag.name))
        else:
            query = query.order_by(asc(Tag.name))

    # Get paginated results
    results = query.offset(skip).limit(limit).all()

    # Format the results
    return [
        {
            "id": r[0],
            "name": r[1],
            "post_count": r[2]
        }
        for r in results
    ]