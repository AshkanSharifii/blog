# src/app/crud/post_crud.py
from typing import List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import desc
from src.app.models.post_model import Post
from src.app.models.tag_model import Tag
from src.app.schemas.post_schema import PostCreate, PostUpdate
from src.app.crud.tag_crud import get_or_create_tags
from src.app.utils.file import find_images_in_content, delete_image_from_minio, extract_filename_from_path


# ---------- read ----------
def get_posts(
        db: Session,
        skip: int = 0,
        limit: int = 100,
        tag_name: Optional[str] = None,
        show_archived: bool = False,
        show_inactive: bool = False,
        sort_by: str = "created_at",
        sort_desc: bool = True  # Default to newest first
) -> List[Post]:
    """
    Get a list of posts with various filters and sorting options.

    Args:
        db: Database session
        skip: Number of posts to skip (for pagination)
        limit: Maximum number of posts to return
        tag_name: Filter posts by tag
        show_archived: Whether to include archived posts
        show_inactive: Whether to include inactive posts
        sort_by: Field to sort by (created_at, updated_at, title)
        sort_desc: Whether to sort in descending order (newest first if sorting by date)

    Returns:
        List of Post objects
    """
    q = db.query(Post)

    # Apply tag filter if specified
    if tag_name:
        q = q.join(Post.tags).filter(Tag.name == tag_name)

    # Apply archive filter
    if not show_archived:
        q = q.filter(Post.is_archived == False)

    # Apply active filter
    if not show_inactive:
        q = q.filter(Post.is_active == True)

    # Apply sorting
    if sort_by in ["created_at", "updated_at", "title"]:
        sort_column = getattr(Post, sort_by)
        if sort_desc:
            q = q.order_by(desc(sort_column))
        else:
            q = q.order_by(sort_column)
    else:
        # Default sort is by created_at desc (newest first)
        q = q.order_by(desc(Post.created_at))

    return q.offset(skip).limit(limit).all()


def get_post(db: Session, post_id: int) -> Optional[Post]:
    return db.query(Post).filter(Post.id == post_id).first()


# ---------- write ----------
def create_post(
        db: Session,
        obj_in: PostCreate,
        image_url: Optional[str] = None,  # Now just a filename
) -> Post:
    tag_names = (
        [t.strip() for t in obj_in.tags.split(",") if t.strip()]
        if obj_in.tags
        else []
    )

    post = Post(
        title=obj_in.title,
        content=obj_in.content,
        image_url=image_url,  # This might be None
        is_active=obj_in.is_active if obj_in.is_active is not None else True,
        is_archived=obj_in.is_archived if obj_in.is_archived is not None else False,
    )
    if tag_names:
        post.tags = get_or_create_tags(db, tag_names)

    db.add(post)
    db.commit()
    db.refresh(post)
    return post


def update_post(
        db: Session,
        post: Post,
        obj_in: PostCreate,
        image_url: Optional[str] = None,  # Now just a filename
        manage_content_images: bool = False,
) -> Post:
    """
    Update a post with new content, optionally managing content images.

    Args:
        db: Database session
        post: Post object to update
        obj_in: New post data
        image_url: New cover image filename (if any)
        manage_content_images: If True, will clean up unused images in content
    """
    # If managing content images, find images in old and new content
    old_content_images = set()
    if manage_content_images:
        old_content_images = set(find_images_in_content(post.content))

    # Update post fields
    post.title = obj_in.title
    post.content = obj_in.content

    # Update the new fields
    if obj_in.is_active is not None:
        post.is_active = obj_in.is_active
    if obj_in.is_archived is not None:
        post.is_archived = obj_in.is_archived

    if image_url is not None:
        # If we have a new cover image and an old one, delete the old one
        if post.image_url and post.image_url != image_url:
            try:
                delete_image_from_minio(post.image_url, image_type="cover")
            except Exception as e:
                # Just log the error but continue with the update
                print(f"Error deleting old cover image: {e}")

        post.image_url = image_url  # Store the filename directly

    # Update tags if sent
    if obj_in.tags is not None:
        tag_names = [t.strip() for t in obj_in.tags.split(",") if t.strip()]
        post.tags = get_or_create_tags(db, tag_names)

    # Commit changes
    db.commit()
    db.refresh(post)

    # If managing content images, clean up unused images
    if manage_content_images:
        new_content_images = set(find_images_in_content(post.content))
        unused_images = old_content_images - new_content_images

        # Delete any images that are no longer used in the content
        for img_filename in unused_images:
            try:
                delete_image_from_minio(img_filename, image_type="content")
            except Exception as e:
                # Just log the error but continue
                print(f"Error deleting unused content image: {e}")

    return post


def archive_post(db: Session, post: Post) -> Post:
    """
    Archive a post but don't delete it.

    Args:
        db: Database session
        post: Post object to archive

    Returns:
        The updated Post object
    """
    post.is_archived = True
    db.commit()
    db.refresh(post)
    return post


def unarchive_post(db: Session, post: Post) -> Post:
    """
    Unarchive a previously archived post.

    Args:
        db: Database session
        post: Post object to unarchive

    Returns:
        The updated Post object
    """
    post.is_archived = False
    db.commit()
    db.refresh(post)
    return post


def change_post_active_status(db: Session, post: Post, is_active: bool) -> Post:
    """
    Change the active status of a post.

    Args:
        db: Database session
        post: Post object to update
        is_active: New active status

    Returns:
        The updated Post object
    """
    post.is_active = is_active
    db.commit()
    db.refresh(post)
    return post


def delete_post(db: Session, post: Post, delete_images: bool = False) -> None:
    """
    Delete a post and optionally its associated images.

    Args:
        db: Database session
        post: Post object to delete
        delete_images: If True, will delete cover and content images
    """
    if delete_images:
        # Delete cover image if it exists
        if post.image_url:
            try:
                delete_image_from_minio(post.image_url, image_type="cover")
            except Exception as e:
                print(f"Error deleting cover image: {e}")

        # Delete content images
        content_images = find_images_in_content(post.content)
        for img_filename in content_images:
            try:
                delete_image_from_minio(img_filename, image_type="content")
            except Exception as e:
                print(f"Error deleting content image: {e}")

    # Delete the post
    db.delete(post)
    db.commit()