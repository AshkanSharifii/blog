# src/app/api/api_v1/endpoints/images.py
from typing import List, Optional
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, Query, Path, Response
from sqlalchemy.orm import Session
from io import BytesIO
import os

from src.app.database.database import get_db
from src.app.models.user_model import User
from src.app.models.post_model import Post
from src.app.api.deps import get_current_user
from src.app.utils.file import (
    save_image, save_multiple_images, delete_image_from_minio,
    extract_filename_from_path, get_image_full_url
)
from src.app.core.config import settings
from src.app.services.minio_client import MinioClient

router = APIRouter()


@router.post("/upload", response_model=dict)
async def upload_single_image(
        image: UploadFile = File(...),
        image_type: str = Query("content", description="Type of image: 'cover' or 'content'"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Upload a single image and return its filename.

    - image_type: 'cover' for post cover images, 'content' for in-content images
    Requires authentication.
    """
    if not image.content_type or not image.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="File must be an image"
        )

    # Save the image and get filename
    filename = save_image(image, image_type=image_type)
    if not filename:
        raise HTTPException(
            status_code=500,
            detail="Failed to save image"
        )

    # Convert filename to full URL
    full_url = get_image_full_url(filename, image_type)

    return {
        "filename": filename,
        "type": image_type,
        "url": full_url
    }


@router.post("/upload-multiple", response_model=dict)
async def upload_multiple_images(
        images: List[UploadFile] = File(...),
        image_type: str = Query("content", description="Type of images: 'cover' or 'content'"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Upload multiple images and return a list of their filenames.

    - image_type: 'cover' for post cover images, 'content' for in-content images
    Requires authentication.
    """
    # Validate all files are images
    for img in images:
        if not img.content_type or not img.content_type.startswith("image/"):
            raise HTTPException(
                status_code=400,
                detail=f"File '{img.filename}' is not an image"
            )

    filenames = save_multiple_images(images, image_type=image_type)

    if not filenames:
        raise HTTPException(
            status_code=500,
            detail="Failed to save images"
        )

    # Convert filenames to full URLs
    urls = [get_image_full_url(filename, image_type) for filename in filenames]

    return {
        "filenames": filenames,
        "urls": urls,
        "type": image_type
    }


@router.delete("/{filename}", response_model=dict)
async def delete_image(
        filename: str = Path(..., description="The filename of the image to delete"),
        image_type: str = Query("content", description="Type of image: 'cover' or 'content'"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Delete an image by its filename.

    - filename: The filename to delete (e.g., "96e48b9f30f84bde91480421f36a4bed.jpg")
    - image_type: Either "cover" or "content"
    """
    # Extract just the filename if a full URL was provided
    filename = extract_filename_from_path(filename) or filename

    success = delete_image_from_minio(filename, image_type)

    if not success:
        raise HTTPException(
            status_code=404,
            detail="Image not found or could not be deleted"
        )

    return {"success": True, "message": "Image deleted successfully"}


@router.get("/list", response_model=dict)
async def list_images(
        image_type: Optional[str] = Query(None, description="Filter by type: 'cover' or 'content'"),
        show_archived_post_images: bool = Query(False, description="Include images from archived posts"),
        show_inactive_post_images: bool = Query(False, description="Include images from inactive posts"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    List all images, optionally filtered by type and post status.

    - image_type: Optional filter for image type
    - show_archived_post_images: Whether to include images from archived posts
    - show_inactive_post_images: Whether to include images from inactive posts
    """
    from src.app.services.minio_client import MinioClient
    import os

    # Initialize MinIO client
    minio_client = MinioClient(
        url=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        blog_bucket=settings.minio_bucket,
    ).client

    try:
        images = []
        prefix = f"{image_type}/" if image_type else None

        objects = minio_client.list_objects(settings.minio_bucket, prefix=prefix, recursive=True)

        # Get post image mappings to filter by post status if requested
        post_cover_images = {}
        if image_type == "cover" or image_type is None:
            # First, get a list of post cover images based on status filters
            query = db.query(Post.image_url, Post.is_archived, Post.is_active)

            if not show_archived_post_images:
                query = query.filter(Post.is_archived == False)

            if not show_inactive_post_images:
                query = query.filter(Post.is_active == True)

            post_covers = query.all()

            # Create a mapping of cover image filename to post status
            for cover_url, is_archived, is_active in post_covers:
                if cover_url:  # Skip posts without cover images
                    filename = extract_filename_from_path(cover_url)
                    if filename:
                        post_cover_images[filename] = {
                            "is_archived": is_archived,
                            "is_active": is_active
                        }

        for obj in objects:
            # Extract filename from path
            path = obj.object_name
            filename = os.path.basename(path)

            # Determine type from path
            obj_type = "content"
            if path.startswith("cover/"):
                obj_type = "cover"

                # Skip cover images based on post status filters
                if obj_type == "cover" and not (show_archived_post_images and show_inactive_post_images):
                    # If image is not in our mapping and we're filtering, it could be orphaned or not associated
                    # with a post. We'll include it for admin purposes.
                    if filename in post_cover_images:
                        post_status = post_cover_images[filename]

                        # Skip archived post images if not showing them
                        if not show_archived_post_images and post_status.get("is_archived", False):
                            continue

                        # Skip inactive post images if not showing them
                        if not show_inactive_post_images and not post_status.get("is_active", True):
                            continue

            # Generate full URL
            full_url = get_image_full_url(filename, obj_type)

            images.append({
                "filename": filename,
                "path": path,
                "url": full_url,
                "type": obj_type,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat()
            })

        return {
            "images": images,
            "count": len(images)
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list images: {str(e)}"
        )


@router.get("/serve/{image_type}/{filename}", response_class=Response)
async def serve_image(
        image_type: str = Path(..., description="Type of image: 'cover' or 'content'"),
        filename: str = Path(..., description="Image filename"),
        db: Session = Depends(get_db),
):
    """
    Serve an image directly from MinIO storage.

    This endpoint allows direct image serving without redirecting to MinIO,
    which is useful when MinIO is not publicly accessible or when you need
    to control access to images.

    Args:
        image_type: Either "cover" or "content"
        filename: The image filename

    Returns:
        The image with appropriate Content-Type header
    """
    try:
        # Initialize MinIO client
        minio_client = MinioClient(
            url=settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            blog_bucket=settings.minio_bucket,
        ).client

        # Construct the full object path
        object_name = f"{image_type}/{filename}"

        try:
            # Get the object from MinIO
            response = minio_client.get_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name
            )

            # Read the entire content
            content = BytesIO(response.read())

            # Determine content type based on file extension
            content_type = "image/jpeg"  # Default content type
            if filename.lower().endswith(".png"):
                content_type = "image/png"
            elif filename.lower().endswith(".gif"):
                content_type = "image/gif"
            elif filename.lower().endswith(".svg"):
                content_type = "image/svg+xml"
            elif filename.lower().endswith(".webp"):
                content_type = "image/webp"

            # Return the image with appropriate content type
            return Response(
                content=content.getvalue(),
                media_type=content_type,
                headers={
                    "Cache-Control": "max-age=86400"  # Cache for 24 hours
                }
            )

        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"Image not found: {str(e)}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error serving image: {str(e)}"
        )


@router.get("/serve-post-image/{post_id}/{image_type}/{filename}", response_class=Response)
async def serve_post_image(
        post_id: int = Path(..., description="Post ID"),
        image_type: str = Path(..., description="Type of image: 'cover' or 'content'"),
        filename: str = Path(..., description="Image filename"),
        db: Session = Depends(get_db),
):
    """
    Serve an image associated with a specific post, respecting post status.

    This endpoint checks if the post is active and not archived before serving the image.
    For public access where you want to respect post status.

    Args:
        post_id: The ID of the post
        image_type: Either "cover" or "content"
        filename: The image filename

    Returns:
        The image with appropriate Content-Type header if the post is active and not archived
    """
    # Check if post exists and is active/not archived
    post = db.query(Post).filter(Post.id == post_id).first()

    if not post:
        raise HTTPException(
            status_code=404,
            detail="Post not found"
        )

    # Check post status - only serve if active and not archived
    if post.is_archived:
        raise HTTPException(
            status_code=403,
            detail="This post is archived"
        )

    if not post.is_active:
        raise HTTPException(
            status_code=403,
            detail="This post is inactive"
        )

    # If it's a cover image, verify it belongs to the post
    if image_type == "cover" and post.image_url:
        post_cover_filename = extract_filename_from_path(post.image_url)
        if post_cover_filename != filename:
            raise HTTPException(
                status_code=404,
                detail="Image not found for this post"
            )

    # For content images, we could check if they appear in the content
    # but that would be expensive - for now we'll just serve the image

    # Now proceed with serving the image
    try:
        # Initialize MinIO client
        minio_client = MinioClient(
            url=settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            blog_bucket=settings.minio_bucket,
        ).client

        # Construct the full object path
        object_name = f"{image_type}/{filename}"

        try:
            # Get the object from MinIO
            response = minio_client.get_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name
            )

            # Read the entire content
            content = BytesIO(response.read())

            # Determine content type based on file extension
            content_type = "image/jpeg"  # Default content type
            if filename.lower().endswith(".png"):
                content_type = "image/png"
            elif filename.lower().endswith(".gif"):
                content_type = "image/gif"
            elif filename.lower().endswith(".svg"):
                content_type = "image/svg+xml"
            elif filename.lower().endswith(".webp"):
                content_type = "image/webp"

            # Return the image with appropriate content type
            return Response(
                content=content.getvalue(),
                media_type=content_type,
                headers={
                    "Cache-Control": "max-age=86400"  # Cache for 24 hours
                }
            )

        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"Image not found: {str(e)}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error serving image: {str(e)}"
        )


@router.get("/info/{image_type}/{filename}", response_model=dict)
async def get_image_info(
        image_type: str = Path(..., description="Type of image: 'cover' or 'content'"),
        filename: str = Path(..., description="Image filename"),
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Get information about a specific image.

    Args:
        image_type: Either "cover" or "content"
        filename: The image filename

    Returns:
        Dict with image information
    """
    try:
        # Initialize MinIO client
        minio_client = MinioClient(
            url=settings.minio_endpoint,
            access_key=settings.minio_root_user,
            secret_key=settings.minio_root_password,
            blog_bucket=settings.minio_bucket,
        ).client

        # Extract just the filename if a full URL was provided
        filename = extract_filename_from_path(filename) or filename

        # Construct the full object path
        object_name = f"{image_type}/{filename}"

        try:
            # Get the object stats
            stats = minio_client.stat_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name
            )

            # Generate full URL
            full_url = get_image_full_url(filename, image_type)

            # Serve URL (via the serve endpoint)
            serve_url = f"/api/v1/images/serve/{image_type}/{filename}"

            # Check if this image is associated with any posts
            associated_posts = []
            if image_type == "cover":
                # Query posts that use this image as cover
                posts = db.query(Post).filter(Post.image_url.contains(filename)).all()
                associated_posts = [{
                    "id": post.id,
                    "title": post.title,
                    "is_active": post.is_active,
                    "is_archived": post.is_archived
                } for post in posts]

            return {
                "filename": filename,
                "path": object_name,
                "type": image_type,
                "url": full_url,
                "serve_url": serve_url,
                "size": stats.size,
                "content_type": stats.content_type,
                "last_modified": stats.last_modified.isoformat(),
                "associated_posts": associated_posts
            }

        except Exception as e:
            raise HTTPException(
                status_code=404,
                detail=f"Image not found: {str(e)}"
            )

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error getting image info: {str(e)}"
        )


@router.get("/orphaned", response_model=dict)
async def find_orphaned_images(
        db: Session = Depends(get_db),
        current_user: User = Depends(get_current_user),
):
    """
    Find images that are not associated with any active post.

    This helps identify images that can be safely deleted to free up storage.

    Returns:
        Dict with lists of orphaned cover and content images
    """
    from src.app.services.minio_client import MinioClient
    import os
    from src.app.utils.file import find_images_in_content

    # Initialize MinIO client
    minio_client = MinioClient(
        url=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password,
        blog_bucket=settings.minio_bucket,
    ).client

    try:
        # Get all images from storage
        all_cover_images = []
        all_content_images = []

        # Get cover images
        cover_objects = minio_client.list_objects(settings.minio_bucket, prefix="cover/", recursive=True)
        for obj in cover_objects:
            filename = os.path.basename(obj.object_name)
            all_cover_images.append({
                "filename": filename,
                "path": obj.object_name,
                "url": get_image_full_url(filename, "cover"),
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat()
            })

        # Get content images
        content_objects = minio_client.list_objects(settings.minio_bucket, prefix="content/", recursive=True)
        for obj in content_objects:
            filename = os.path.basename(obj.object_name)
            all_content_images.append({
                "filename": filename,
                "path": obj.object_name,
                "url": get_image_full_url(filename, "content"),
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat()
            })

        # Get images used in posts
        used_cover_images = set()
        used_content_images = set()

        # Get all posts (including archived and inactive)
        posts = db.query(Post).all()

        for post in posts:
            # Add cover image
            if post.image_url:
                cover_filename = extract_filename_from_path(post.image_url)
                if cover_filename:
                    used_cover_images.add(cover_filename)

            # Add content images
            content_filenames = find_images_in_content(post.content)
            for filename in content_filenames:
                content_filename = extract_filename_from_path(filename)
                if content_filename:
                    used_content_images.add(content_filename)

        # Find orphaned images
        orphaned_cover_images = []
        for image in all_cover_images:
            if image["filename"] not in used_cover_images:
                orphaned_cover_images.append(image)

        orphaned_content_images = []
        for image in all_content_images:
            if image["filename"] not in used_content_images:
                orphaned_content_images.append(image)

        return {
            "orphaned_cover_images": orphaned_cover_images,
            "orphaned_content_images": orphaned_content_images,
            "total_orphaned": len(orphaned_cover_images) + len(orphaned_content_images)
        }

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to find orphaned images: {str(e)}"
        )