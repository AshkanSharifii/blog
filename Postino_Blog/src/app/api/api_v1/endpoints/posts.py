# src/app/api/api_v1/endpoints/posts.py
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Form, UploadFile, File, Query, Path
from sqlalchemy.orm import Session
import logging
import json
import re

from src.app.database.database import get_db
from src.app.schemas.post_schema import PostCreate, PostUpdate, PostOut
from src.app.crud import post_crud
from src.app.utils.file import (
    save_image, save_multiple_images, find_images_in_content,
    delete_image_from_minio, extract_filename_from_path,
    get_image_full_url
)
from src.app.models.user_model import User
from src.app.api.deps import get_current_user

router = APIRouter()
logger = logging.getLogger(__name__)


# ---------- helpers ----------
def _make_out(p) -> PostOut:
    """
    Convert a Post model to a PostOut schema.
    Converts image_url to a full URL if it's just a filename.
    Includes the new archive and active status fields.
    """
    # Convert the image_url to a full URL if it's just a filename
    image_url = p.image_url
    if image_url and not image_url.startswith(('http://', 'https://')):
        image_url = get_image_full_url(image_url, "cover")

    # Determine status based on is_archived and is_active
    status = "published"
    if p.is_archived:
        status = "archived"
    elif not p.is_active:
        status = "inactive"

    return PostOut(
        id=p.id,
        title=p.title,
        content=p.content,
        image_url=image_url,  # Use the full URL version
        tags=[t.name for t in p.tags],
        created_at=p.created_at,
        updated_at=p.updated_at,
        is_archived=p.is_archived,
        is_active=p.is_active,
        status=status
    )


def _insert_images_into_content(content: str, filenames: List[str]) -> str:
    """
    Insert image references into content.
    Converts filenames to full URLs before inserting.
    """
    if not filenames:
        return content

    updated_content = content

    # Add each image reference at the end of the content
    for filename in filenames:
        # Convert filename to full URL
        img_url = get_image_full_url(filename, "content")
        updated_content += f"\n\n![Image]({img_url})\n"

    return updated_content


def _replace_image_in_content(content: str, old_filename: str, new_filename: str) -> str:
    """Replace a specific image reference in content with a new filename."""
    # Convert filenames to full URLs
    old_url = get_image_full_url(old_filename, "content")
    new_url = get_image_full_url(new_filename, "content")

    pattern = fr'(!\[.*?\])\({re.escape(old_url)}\)'
    return re.sub(pattern, fr'\1({new_url})', content)


def _remove_image_from_content(content: str, filename: str) -> str:
    """Remove a specific image reference from content."""
    # Convert filename to full URL
    img_url = get_image_full_url(filename, "content")

    pattern = fr'!\[.*?\]\({re.escape(img_url)}\)(\s*\n*)?'
    return re.sub(pattern, '', content)


# ---------- routes ----------
@router.get("/", response_model=List[PostOut])
def read_posts(
        skip: int = 0,
        limit: int = 100,
        tag: Optional[str] = None,
        show_archived: bool = Query(False, description="Whether to include archived posts"),
        show_inactive: bool = Query(False, description="Whether to include inactive posts"),
        sort_by: str = Query("created_at", description="Field to sort by (created_at, updated_at, title)"),
        sort_desc: bool = Query(True, description="Sort in descending order (newest first if sorting by date)"),
        db: Session = Depends(get_db),
):
    """
    Get a list of blog posts.

    - skip: Number of posts to skip (for pagination)
    - limit: Maximum number of posts to return
    - tag: Filter posts by tag
    - show_archived: Whether to include archived posts
    - show_inactive: Whether to include inactive posts
    - sort_by: Field to sort by (created_at, updated_at, title)
    - sort_desc: Whether to sort in descending order (newest first if sorting by date)
    """
    posts = post_crud.get_posts(
        db,
        skip=skip,
        limit=limit,
        tag_name=tag,
        show_archived=show_archived,
        show_inactive=show_inactive,
        sort_by=sort_by,
        sort_desc=sort_desc
    )
    return [_make_out(p) for p in posts]


@router.get("/{post_id}", response_model=PostOut)
def read_post(post_id: int, db: Session = Depends(get_db)):
    """
    Get a single blog post by ID.

    - post_id: The ID of the post to retrieve
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")
    return _make_out(post)


@router.get("/{post_id}/images", response_model=dict)
def get_post_images(
        post_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Get all images associated with a blog post:
    - Cover image (if any)
    - Content images extracted from the post content
    Returns the full URLs for all images.
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Extract content images
    content_image_filenames = find_images_in_content(post.content)

    # Convert all filenames to full URLs
    content_images = [
        get_image_full_url(filename, "content")
        for filename in content_image_filenames
    ]

    # Get cover image URL
    cover_image = None
    if post.image_url:
        cover_image = get_image_full_url(post.image_url, "cover")

    return {
        "post_id": post_id,
        "cover_image": cover_image,
        "content_images": content_images,
        "total_images": len(content_images) + (1 if cover_image else 0)
    }


@router.post("/", response_model=PostOut)
def create_post(
        title: str = Form(...),
        content: str = Form(...),
        tags: Optional[str] = Form(None),
        is_active: bool = Form(True),
        is_archived: bool = Form(False),
        cover_image: Optional[UploadFile] = File(None),
        content_images: Optional[List[UploadFile]] = File(None),
        content_image_positions: Optional[str] = Form(None),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Create a new blog post with support for a cover image and multiple content images.

    - title: Post title
    - content: Post content (can include image references like ![Alt](filename.jpg))
    - tags: Comma-separated tags
    - is_active: Whether the post is active and visible to users
    - is_archived: Whether the post is archived
    - cover_image: Cover image file
    - content_images: Additional content images to be available for the post
    - content_image_positions: Optional JSON string containing positions to insert images
      Format: {"positions": [{"index": cursor_position_int, "image_index": content_image_index_int}, ...]}

    Images are stored to MinIO and referenced by full URLs in the response.
    """
    # Save cover image if provided
    cover_img_filename = None
    if cover_image and cover_image.filename:
        cover_img_filename = save_image(cover_image, "cover")

    # Save content images if provided
    content_img_filenames = []
    if content_images:
        content_img_filenames = save_multiple_images(
            [img for img in content_images if img and img.filename],
            "content"
        )

    # Process content with image positions (if provided)
    final_content = content
    if content_img_filenames:
        if content_image_positions:
            try:
                positions_data = json.loads(content_image_positions)
                if "positions" in positions_data and isinstance(positions_data["positions"], list):
                    # Sort positions in reverse order to avoid index shifting
                    sorted_positions = sorted(
                        positions_data["positions"],
                        key=lambda x: x.get("index", 0),
                        reverse=True
                    )

                    # Insert images at the specified positions
                    for pos in sorted_positions:
                        index = pos.get("index", 0)
                        img_index = pos.get("image_index", 0)

                        if 0 <= img_index < len(content_img_filenames):
                            img_filename = content_img_filenames[img_index]
                            # Convert filename to full URL
                            img_url = get_image_full_url(img_filename, "content")
                            img_markdown = f"\n\n![Image]({img_url})\n\n"

                            final_content = (
                                    final_content[:index] +
                                    img_markdown +
                                    final_content[index:]
                            )
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"Error processing image positions: {str(e)}")
                # If we couldn't process positions, just append images at the end
                final_content = _insert_images_into_content(content, content_img_filenames)
        else:
            # No positions provided, just append at the end
            final_content = _insert_images_into_content(content, content_img_filenames)

    # Create post with the filename (not the full URL)
    obj_in = PostCreate(
        title=title,
        content=final_content,
        tags=tags,
        is_active=is_active,
        is_archived=is_archived
    )
    post = post_crud.create_post(db, obj_in=obj_in, image_url=cover_img_filename)

    # Return with full URLs
    return _make_out(post)


@router.put("/{post_id}", response_model=PostOut)
def update_post(
        post_id: int,
        title: str = Form(...),
        content: str = Form(...),
        tags: Optional[str] = Form(None),
        is_active: bool = Form(True),
        is_archived: bool = Form(False),
        cover_image: Optional[UploadFile] = File(None),
        content_images: Optional[List[UploadFile]] = File(None),
        content_image_positions: Optional[str] = Form(None),
        keep_cover_image: bool = Form(True),
        delete_unused_images: bool = Form(False),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Update a blog post with images.

    - title: Updated post title
    - content: Updated post content
    - tags: Updated comma-separated tags
    - is_active: Whether the post is active and visible to users
    - is_archived: Whether the post is archived
    - cover_image: New cover image (if changing)
    - content_images: New content images
    - content_image_positions: Optional JSON string with positions to insert images
    - keep_cover_image: Whether to keep existing cover image if no new one provided
    - delete_unused_images: Whether to delete images that are no longer used in content
    """
    # Get existing post
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Handle cover image
    cover_img_filename = None
    if cover_image and cover_image.filename:
        # Delete old cover image if it exists
        if post.image_url:
            delete_image_from_minio(post.image_url, "cover")

        # Save new cover image and get the filename
        cover_img_filename = save_image(cover_image, "cover")
    elif keep_cover_image:
        # Keep existing cover image
        cover_img_filename = post.image_url

    # Save content images if provided
    content_img_filenames = []
    if content_images:
        content_img_filenames = save_multiple_images(
            [img for img in content_images if img and img.filename],
            "content"
        )

    # Process content with image positions (if provided)
    final_content = content
    if content_img_filenames:
        if content_image_positions:
            try:
                positions_data = json.loads(content_image_positions)
                if "positions" in positions_data and isinstance(positions_data["positions"], list):
                    # Sort positions in reverse order to avoid index shifting
                    sorted_positions = sorted(
                        positions_data["positions"],
                        key=lambda x: x.get("index", 0),
                        reverse=True
                    )

                    # Insert images at the specified positions
                    for pos in sorted_positions:
                        index = pos.get("index", 0)
                        img_index = pos.get("image_index", 0)

                        if 0 <= img_index < len(content_img_filenames):
                            img_filename = content_img_filenames[img_index]
                            # Convert filename to full URL
                            img_url = get_image_full_url(img_filename, "content")
                            img_markdown = f"\n\n![Image]({img_url})\n\n"

                            final_content = (
                                    final_content[:index] +
                                    img_markdown +
                                    final_content[index:]
                            )
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"Error processing image positions: {str(e)}")
                # If we couldn't process positions, just append images at the end
                final_content = _insert_images_into_content(content, content_img_filenames)
        else:
            # No positions provided, just append at the end
            final_content = _insert_images_into_content(content, content_img_filenames)

    # Update post with the filename (not the full URL)
    obj_in = PostUpdate(
        title=title,
        content=final_content,
        tags=tags,
        is_active=is_active,
        is_archived=is_archived
    )
    post = post_crud.update_post(
        db,
        post=post,
        obj_in=obj_in,
        image_url=cover_img_filename,
        manage_content_images=delete_unused_images
    )

    # Return with full URLs
    return _make_out(post)


@router.patch("/{post_id}/archive", response_model=PostOut)
def archive_post(
        post_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Archive a post.

    - post_id: The ID of the post to archive
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post = post_crud.archive_post(db, post)
    return _make_out(post)


@router.patch("/{post_id}/unarchive", response_model=PostOut)
def unarchive_post(
        post_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Unarchive a post.

    - post_id: The ID of the post to unarchive
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post = post_crud.unarchive_post(db, post)
    return _make_out(post)


@router.patch("/{post_id}/activate", response_model=PostOut)
def activate_post(
        post_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Activate a post (make it visible to users).

    - post_id: The ID of the post to activate
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post = post_crud.change_post_active_status(db, post, True)
    return _make_out(post)


@router.patch("/{post_id}/deactivate", response_model=PostOut)
def deactivate_post(
        post_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Deactivate a post (hide it from users).

    - post_id: The ID of the post to deactivate
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    post = post_crud.change_post_active_status(db, post, False)
    return _make_out(post)


@router.delete("/{post_id}", status_code=204)
def delete_post(
        post_id: int,
        delete_images: bool = Query(True, description="Whether to also delete associated images"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Delete a post and optionally its associated images.

    - delete_images: If True (default), deletes all images associated with the post
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    if delete_images:
        # Delete cover image
        if post.image_url:
            delete_image_from_minio(post.image_url, "cover")

        # Delete content images
        content_images = find_images_in_content(post.content)
        for img in content_images:
            delete_image_from_minio(img, "content")

    # Delete the post
    db.delete(post)
    db.commit()


@router.post("/{post_id}/images", response_model=dict)
def add_images_to_post(
        post_id: int,
        images: List[UploadFile] = File(...),
        image_type: str = Query("content", description="Type of images to add"),
        auto_insert: bool = Query(True, description="Whether to auto-insert content images into post"),
        positions: Optional[str] = Query(None, description="JSON string with positions to insert images"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Add images to an existing post.

    - images: Image files to upload
    - image_type: Either "cover" or "content"
    - auto_insert: Whether to automatically insert content images into post content
    - positions: Optional JSON string with positions to insert images
      Format: {"positions": [{"index": cursor_position_int, "image_index": content_image_index_int}, ...]}

    Returns the filenames of the uploaded images.
    """
    # Verify post exists
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Save the images
    filenames = save_multiple_images(
        [img for img in images if img and img.filename],
        image_type
    )

    if not filenames:
        raise HTTPException(
            status_code=400,
            detail="No valid images were provided"
        )

    # If it's a cover image, update the post
    if image_type == "cover" and filenames:
        # Delete old cover image if exists
        if post.image_url:
            delete_image_from_minio(post.image_url, "cover")

        # Update post with new cover image
        post.image_url = filenames[0]
        db.commit()
        db.refresh(post)

    # If auto_insert is enabled and we have content images, insert them
    elif image_type == "content" and auto_insert:
        if positions:
            try:
                # Process positions similar to create_post and update_post
                final_content = post.content
                positions_data = json.loads(positions)

                if "positions" in positions_data and isinstance(positions_data["positions"], list):
                    sorted_positions = sorted(
                        positions_data["positions"],
                        key=lambda x: x.get("index", 0),
                        reverse=True
                    )

                    for pos in sorted_positions:
                        index = pos.get("index", 0)
                        img_index = pos.get("image_index", 0)

                        if 0 <= img_index < len(filenames):
                            img_filename = filenames[img_index]
                            # Convert filename to full URL
                            img_url = get_image_full_url(img_filename, "content")
                            img_markdown = f"\n\n![Image]({img_url})\n\n"

                            final_content = (
                                    final_content[:index] +
                                    img_markdown +
                                    final_content[index:]
                            )

                    post.content = final_content
                    db.commit()
                    db.refresh(post)
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                # If positions processing fails, just append at the end
                post.content = _insert_images_into_content(post.content, filenames)
                db.commit()
                db.refresh(post)
        else:
            # No positions, just append at the end
            post.content = _insert_images_into_content(post.content, filenames)
            db.commit()
            db.refresh(post)

    # Convert all filenames to full URLs for the response
    full_urls = [get_image_full_url(filename, image_type) for filename in filenames]

    # Return results
    return {
        "post_id": post_id,
        "urls": full_urls,
        "filenames": filenames,
        "type": image_type,
        "auto_inserted": auto_insert and image_type == "content"
    }


@router.delete("/{post_id}/images/{filename}", response_model=dict)
def delete_post_image(
        post_id: int,
        filename: str = Path(..., description="The filename of the image to delete"),
        image_type: str = Query("content", description="Type of image: 'cover' or 'content'"),
        update_content: bool = Query(True, description="Whether to update post content"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Delete a specific image from a post.

    - filename: The filename of the image to delete
    - image_type: Either "cover" or "content"
    - update_content: Whether to update post content to remove the image reference
    """
    # Verify post exists
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Extract just the filename if a full URL was provided
    filename = extract_filename_from_path(filename) or filename

    # Check if it's the cover image
    is_cover = False
    if image_type == "cover" and post.image_url == filename:
        is_cover = True

    # For content images, check if the image is actually used in the content
    if image_type == "content" and not is_cover:
        content_images = find_images_in_content(post.content)
        if filename not in content_images:
            raise HTTPException(
                status_code=404,
                detail=f"Image {filename} not found in post content"
            )

    # Delete the image from storage
    success = delete_image_from_minio(filename, image_type)

    if not success:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete image {filename}"
        )

    # Update post if needed
    if is_cover:
        post.image_url = None
    elif update_content and image_type == "content":
        post.content = _remove_image_from_content(post.content, filename)

    db.commit()
    db.refresh(post)

    # Return the full URL of the deleted image for reference
    full_url = get_image_full_url(filename, image_type)

    return {
        "post_id": post_id,
        "filename": filename,
        "url": full_url,
        "image_type": image_type,
        "success": True,
        "content_updated": update_content and not is_cover
    }


@router.put("/{post_id}/images/{old_filename}", response_model=dict)
def replace_post_image(
        post_id: int,
        old_filename: str = Path(..., description="The filename of the image to replace"),
        new_image: UploadFile = File(...),
        image_type: str = Query("content", description="Type of image: 'cover' or 'content'"),
        update_content: bool = Query(True, description="Whether to update post content references"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Replace an image in a post with a new one.

    - old_filename: The filename of the image to replace
    - new_image: The new image file
    - image_type: Either "cover" or "content"
    - update_content: Whether to update post content to reference the new file
    """
    # Verify post exists
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Extract just the filename if a full URL was provided
    old_filename = extract_filename_from_path(old_filename) or old_filename

    # Check if it's the cover image
    is_cover = False
    if image_type == "cover" and post.image_url == old_filename:
        is_cover = True

    # For content images, check if the image is actually used in the content
    if image_type == "content" and not is_cover:
        content_images = find_images_in_content(post.content)
        if old_filename not in content_images:
            raise HTTPException(
                status_code=404,
                detail=f"Image {old_filename} not found in post content"
            )

    # Upload the new image
    new_filename = save_image(new_image, image_type)

    if not new_filename:
        raise HTTPException(
            status_code=500,
            detail="Failed to save new image"
        )

    # Delete the old image from storage
    delete_image_from_minio(old_filename, image_type)

    # Update post if needed
    if is_cover:
        post.image_url = new_filename
    elif update_content and image_type == "content":
        post.content = _replace_image_in_content(post.content, old_filename, new_filename)

    db.commit()
    db.refresh(post)

    # Get full URLs for the response
    old_url = get_image_full_url(old_filename, image_type)
    new_url = get_image_full_url(new_filename, image_type)

    return {
        "post_id": post_id,
        "old_filename": old_filename,
        "new_filename": new_filename,
        "old_url": old_url,
        "new_url": new_url,
        "image_type": image_type,
        "success": True,
        "content_updated": update_content and not is_cover
    }


@router.put("/{post_id}/cover-image", response_model=PostOut)
def update_post_cover_image(
        post_id: int,
        cover_image: UploadFile = File(...),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Update just the cover image of a post.

    - cover_image: The new cover image file
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Save the new cover image
    if not cover_image or not cover_image.filename:
        raise HTTPException(
            status_code=400,
            detail="No valid cover image was provided"
        )

    cover_img_filename = save_image(cover_image, "cover")

    # Delete the old cover image if it exists
    if post.image_url:
        delete_image_from_minio(post.image_url, "cover")

    # Update just the image_url field with the filename (not the full URL)
    post.image_url = cover_img_filename
    db.commit()
    db.refresh(post)

    # Return with full URLs
    return _make_out(post)


@router.delete("/{post_id}/cover-image", response_model=PostOut)
def delete_post_cover_image(
        post_id: int,
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Remove the cover image from a post.
    """
    post = post_crud.get_post(db, post_id)
    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    # Delete the cover image if it exists
    if post.image_url:
        delete_image_from_minio(post.image_url, "cover")

    # Remove the image_url
    post.image_url = None
    db.commit()
    db.refresh(post)

    # Return with full URLs
    return _make_out(post)