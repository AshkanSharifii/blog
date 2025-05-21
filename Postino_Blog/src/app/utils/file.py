# src/app/utils/file.py
"""
File utilities for managing images in MinIO with flexible URL options.
"""

import os
import uuid
import re
from typing import Optional, List, Any
from io import BytesIO
from urllib.parse import urlparse  # Add this import for urlparse
from fastapi import UploadFile, HTTPException
from minio.error import S3Error

from src.app.core.config import settings
from src.app.services.minio_client import MinioClient

# Initialize MinIO client
_minio_client = MinioClient(
    url=settings.minio_endpoint,
    access_key=settings.minio_root_user,
    secret_key=settings.minio_root_password,
    blog_bucket=settings.minio_bucket,
)
_minio = _minio_client.client

# Configure the base URL for images
# Change this based on your deployment environment
# For local development: "http://localhost:9000/posts"
# For docker internal: "http://minio:9000/posts"
# For production: your domain
IMAGE_BASE_URL = os.environ.get("IMAGE_BASE_URL", "http://localhost:9000/posts")


def get_public_url(object_name: str) -> str:
    """
    Generate a public URL for an object in MinIO.
    This can be configured based on your environment.
    """
    return f"{IMAGE_BASE_URL}/{object_name}"


def save_image(
        image: UploadFile,
        image_type: str = "content",
        return_full_url: bool = False
) -> Optional[str]:
    """
    Save an uploaded image to MinIO and return the filename or full URL.

    Args:
        image: The uploaded image file
        image_type: Either "cover" or "content"
        return_full_url: If True, returns full URL; if False, just the filename

    Returns:
        str: The filename or full URL of the saved image
    """
    if not image or not image.filename:
        return None

    try:
        # Generate a unique filename with original extension
        ext = "jpg"  # Default extension
        if "." in image.filename:
            ext = image.filename.rsplit(".", 1)[-1].lower()

        filename = f"{uuid.uuid4().hex}.{ext}"

        # Read file content
        image.file.seek(0)
        file_content = image.file.read()
        content_length = len(file_content)

        # Reset file position for MinIO upload
        image.file.seek(0)

        # Set content type
        content_type = image.content_type or "image/jpeg"

        # Store in MinIO with path based on image_type
        object_name = f"{image_type}/{filename}"

        _minio.put_object(
            bucket_name=settings.minio_bucket,
            object_name=object_name,
            data=image.file,
            length=content_length,
            content_type=content_type
        )

        # Return either just the filename or the full URL
        if return_full_url:
            return get_public_url(object_name)
        else:
            return filename

    except Exception as e:
        print(f"Error saving image: {str(e)}")
        return None


def save_multiple_images(
        images: List[UploadFile],
        image_type: str = "content",
        return_full_urls: bool = False
) -> List[str]:
    """
    Save multiple uploaded images and return their filenames or full URLs.

    Args:
        images: List of uploaded image files
        image_type: Either "cover" or "content"
        return_full_urls: If True, returns full URLs; if False, just the filenames

    Returns:
        List[str]: List of filenames or URLs of saved images
    """
    if not images:
        return []

    results = []
    for image in images:
        if image and image.filename:
            if is_image_file(image):
                result = save_image(image, image_type, return_full_urls)
                if result:
                    results.append(result)

    return results


def find_images_in_content(content: str) -> List[str]:
    """
    Extract image filenames from Markdown content.

    Args:
        content: Markdown content with image references

    Returns:
        List[str]: List of filenames found in the content
    """
    if not content:
        return []

    # This pattern matches both filenames and full URLs
    # It will capture just the filename part in either case
    pattern = r'!\[.*?\]\(((?:http[s]?://)?(?:[^/]+/)*([^/)]+\.[a-zA-Z0-9]+))\)'

    matches = re.findall(pattern, content)
    # Return just the filename (second group in each match)
    return [match[1] if len(match) > 1 else match[0] for match in matches]


def extract_filename_from_path(path_or_url: str) -> Optional[str]:
    """
    Extract just the filename from a path or URL.

    Args:
        path_or_url: Path or URL containing a filename

    Returns:
        str: The extracted filename or None if not found
    """
    if not path_or_url:
        return None

    try:
        # Handle full URLs
        if path_or_url.startswith(('http://', 'https://')):
            # Extract the path part
            path = urlparse(path_or_url).path
            # Get the filename which is the last part of the path
            filename = os.path.basename(path)
            return filename

        # Handle paths
        if '/' in path_or_url:
            filename = os.path.basename(path_or_url)
            return filename

        # If there's no slash, it might already be just a filename
        return path_or_url

    except Exception:
        return None


def delete_image_from_minio(
        image_identifier: str,
        image_type: str = "content"
) -> bool:
    """
    Delete an image from MinIO storage.

    Args:
        image_identifier: Filename or path of the image to delete
        image_type: Either "cover" or "content"

    Returns:
        bool: True if deletion was successful, False otherwise
    """
    if not image_identifier:
        return False

    try:
        # Extract just the filename if a path or URL was provided
        filename = extract_filename_from_path(image_identifier) or image_identifier

        # Determine the object name
        if "/" in image_identifier:
            # If it already has a path, use it as is
            object_name = image_identifier
        else:
            # Otherwise, add the image_type prefix
            object_name = f"{image_type}/{filename}"

        _minio.remove_object(settings.minio_bucket, object_name)
        return True
    except Exception as e:
        print(f"Error deleting image {image_identifier}: {str(e)}")
        return False


def is_image_file(upload_file: UploadFile) -> bool:
    """
    Check if an uploaded file is a valid image.

    Args:
        upload_file: The uploaded file to check

    Returns:
        bool: True if it's a valid image, False otherwise
    """
    if not upload_file or not upload_file.filename:
        return False

    # Check content type
    if upload_file.content_type and upload_file.content_type.startswith("image/"):
        return True

    # Check file extension
    valid_extensions = {'jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp', 'svg', 'tiff'}
    if "." in upload_file.filename:
        extension = upload_file.filename.rsplit(".", 1)[-1].lower()
        return extension in valid_extensions

    return False


def get_image_full_url(filename: str, image_type: str = "content") -> str:
    """
    Convert a filename to a full URL.

    Args:
        filename: Just the filename (e.g., "96e48b9f30f84bde91480421f36a4bed.jpg")
        image_type: Either "cover" or "content"

    Returns:
        str: The full URL to access the image
    """
    # If it's already a full URL, return as is
    if filename.startswith(('http://', 'https://')):
        return filename

    # If it includes the path already
    if filename.startswith((f"{image_type}/")):
        return f"{IMAGE_BASE_URL}/{filename}"

    # Otherwise, add the image_type prefix
    return f"{IMAGE_BASE_URL}/{image_type}/{filename}"


def replace_image_in_content(content: str, old_filename: str, new_filename: str) -> str:
    """
    Replace a specific image reference in content with a new filename.

    Args:
        content: Post content with image references
        old_filename: Filename to replace
        new_filename: New filename to use

    Returns:
        str: Updated content with replaced image reference
    """
    pattern = fr'(!\[.*?\])\({re.escape(old_filename)}\)'
    return re.sub(pattern, fr'\1({new_filename})', content)


def remove_image_from_content(content: str, filename: str) -> str:
    """
    Remove a specific image reference from content.

    Args:
        content: Post content with image references
        filename: Filename to remove

    Returns:
        str: Updated content with image reference removed
    """
    pattern = fr'!\[.*?\]\({re.escape(filename)}\)(\s*\n*)?'
    return re.sub(pattern, '', content)


def find_unused_images(old_content: str, new_content: str) -> List[str]:
    """
    Find images that were in old content but not in new content.

    Args:
        old_content: Previous post content
        new_content: New post content

    Returns:
        List[str]: List of filenames that are no longer used
    """
    old_images = set(find_images_in_content(old_content))
    new_images = set(find_images_in_content(new_content))

    return list(old_images - new_images)