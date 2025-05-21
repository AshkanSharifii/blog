# src/app/services/minio_client.py
from minio import Minio
from minio.versioningconfig import VersioningConfig, ENABLED
from minio.error import S3Error
import json
import logging
from typing import List, Optional, Dict, Any, Union

logger = logging.getLogger(__name__)


class MinioClient:
    """
    A wrapper for MinIO client that provides simplified bucket management
    and automatic policy configuration.
    """

    def __init__(self, *,
                 url: str,
                 access_key: str,
                 secret_key: str,
                 request_file_bucket: Optional[str] = None,
                 request_image_bucket: Optional[str] = None,
                 service_document_bucket: Optional[str] = None,
                 service_video_bucket: Optional[str] = None,
                 blog_bucket: Optional[str] = None,
                 product_bucket: Optional[str] = None,
                 service_bucket: Optional[str] = None,
                 buckets: Optional[List[str]] = None,
                 public_read: bool = True):
        """
        Initialize MinIO client and create/configure buckets.

        Args:
            url: MinIO server URL (e.g., "minio:9000")
            access_key: MinIO access key
            secret_key: MinIO secret key
            request_file_bucket: Optional bucket name for request files
            request_image_bucket: Optional bucket name for request images
            service_document_bucket: Optional bucket name for service documents
            service_video_bucket: Optional bucket name for service videos
            blog_bucket: Optional bucket name for blog content
            product_bucket: Optional bucket name for product content
            service_bucket: Optional bucket name for service content
            buckets: Optional list of additional bucket names
            public_read: Whether to configure buckets for public read access
        """
        # Store configuration
        self.minio_url = url
        self.access_key = access_key
        self.secret_key = secret_key
        self.public_read = public_read

        # Initialize the client
        self.client = Minio(
            endpoint=self.minio_url,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=False  # Use HTTP instead of HTTPS for local development
        )

        # Collect all buckets to create
        all_buckets = []

        # Add named buckets if provided
        for bucket_name in [
            request_file_bucket,
            request_image_bucket,
            service_document_bucket,
            service_video_bucket,
            blog_bucket,
            product_bucket,
            service_bucket
        ]:
            if bucket_name:
                all_buckets.append(bucket_name)

        # Add buckets from the list if provided
        if buckets:
            all_buckets.extend(buckets)

        # Remove duplicates
        all_buckets = list(set(filter(None, all_buckets)))

        # Create all buckets
        if all_buckets:
            self.make_buckets(all_buckets)

    def make_buckets(self, bucket_names: List[str]) -> Dict[str, bool]:
        """
        Create multiple buckets if they don't exist and configure them.

        Args:
            bucket_names: List of bucket names to create

        Returns:
            Dict mapping bucket names to success status
        """
        results = {}
        for bucket_name in bucket_names:
            try:
                results[bucket_name] = self.make_bucket(bucket_name)
            except Exception as e:
                logger.error(f"Failed to create bucket {bucket_name}: {str(e)}")
                results[bucket_name] = False
        return results

    def make_bucket(self, bucket_name: str) -> bool:
        """
        Create a single bucket if it doesn't exist and configure it.

        Args:
            bucket_name: Name of bucket to create

        Returns:
            bool: True if bucket was created or already exists and is configured
        """
        try:
            # Check if bucket exists
            if not self.client.bucket_exists(bucket_name):
                logger.info(f"Creating bucket: {bucket_name}")
                self.client.make_bucket(bucket_name)

                # Enable versioning
                self.client.set_bucket_versioning(
                    bucket_name,
                    VersioningConfig(ENABLED)
                )
                logger.info(f"Enabled versioning for bucket: {bucket_name}")
            else:
                logger.info(f"Bucket already exists: {bucket_name}")

            # Configure bucket policy if public read is enabled
            if self.public_read:
                self.set_public_read_policy(bucket_name)

            return True

        except S3Error as err:
            logger.error(f"S3Error creating bucket {bucket_name}: {err}")
            raise
        except Exception as err:
            logger.error(f"Unexpected error creating bucket {bucket_name}: {err}")
            raise

    def set_public_read_policy(self, bucket_name: str) -> bool:
        """
        Set a bucket policy to allow public read access.

        Args:
            bucket_name: Name of the bucket to configure

        Returns:
            bool: True if policy was set successfully
        """
        try:
            # Policy document allowing public read access
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": ["*"]},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{bucket_name}/*"]
                    }
                ]
            }

            # Convert policy to JSON string and set it
            self.client.set_bucket_policy(bucket_name, json.dumps(policy))
            logger.info(f"Set public read policy for bucket: {bucket_name}")
            return True

        except S3Error as err:
            logger.error(f"S3Error setting bucket policy for {bucket_name}: {err}")
            raise
        except Exception as err:
            logger.error(f"Unexpected error setting bucket policy for {bucket_name}: {err}")
            raise

    def list_buckets(self) -> List[str]:
        """
        List all buckets.

        Returns:
            List[str]: Names of all buckets
        """
        try:
            buckets = self.client.list_buckets()
            return [bucket.name for bucket in buckets]
        except Exception as e:
            logger.error(f"Error listing buckets: {str(e)}")
            return []

    def bucket_exists(self, bucket_name: str) -> bool:
        """
        Check if a bucket exists.

        Args:
            bucket_name: Name of bucket to check

        Returns:
            bool: True if bucket exists
        """
        try:
            return self.client.bucket_exists(bucket_name)
        except Exception as e:
            logger.error(f"Error checking bucket existence: {str(e)}")
            return False

    def list_objects(self, bucket_name: str, prefix: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        List objects in a bucket.

        Args:
            bucket_name: Name of bucket to list objects from
            prefix: Optional prefix to filter objects by

        Returns:
            List[Dict]: List of object information dictionaries
        """
        try:
            objects = self.client.list_objects(
                bucket_name,
                prefix=prefix,
                recursive=True
            )

            result = []
            for obj in objects:
                result.append({
                    "name": obj.object_name,
                    "size": obj.size,
                    "last_modified": obj.last_modified.isoformat(),
                    "etag": obj.etag,
                })
            return result

        except Exception as e:
            logger.error(f"Error listing objects in bucket {bucket_name}: {str(e)}")
            return []

    def presigned_get_object(self, bucket_name: str, object_name: str, expires: int = 604800) -> Optional[str]:
        """
        Generate a presigned URL for object download.

        Args:
            bucket_name: Name of bucket
            object_name: Name of object
            expires: URL expiration time in seconds (default: 7 days)

        Returns:
            str: Presigned URL or None if error
        """
        try:
            return self.client.presigned_get_object(
                bucket_name,
                object_name,
                expires=expires
            )
        except Exception as e:
            logger.error(f"Error generating presigned URL for {object_name}: {str(e)}")
            return None

    def presigned_put_object(self, bucket_name: str, object_name: str, expires: int = 3600) -> Optional[str]:
        """
        Generate a presigned URL for object upload.

        Args:
            bucket_name: Name of bucket
            object_name: Name of object
            expires: URL expiration time in seconds (default: 1 hour)

        Returns:
            str: Presigned URL or None if error
        """
        try:
            return self.client.presigned_put_object(
                bucket_name,
                object_name,
                expires=expires
            )
        except Exception as e:
            logger.error(f"Error generating presigned upload URL for {object_name}: {str(e)}")
            return None

    def remove_bucket(self, bucket_name: str, force: bool = False) -> bool:
        """
        Remove a bucket.

        Args:
            bucket_name: Name of bucket to remove
            force: If True, remove all objects first

        Returns:
            bool: True if bucket was removed
        """
        try:
            if force:
                # Remove all objects first
                objects = self.client.list_objects(bucket_name, recursive=True)
                for obj in objects:
                    self.client.remove_object(bucket_name, obj.object_name)

            self.client.remove_bucket(bucket_name)
            logger.info(f"Removed bucket: {bucket_name}")
            return True

        except Exception as e:
            logger.error(f"Error removing bucket {bucket_name}: {str(e)}")
            return False

    def get_bucket_policy(self, bucket_name: str) -> Optional[Dict[str, Any]]:
        """
        Get the policy for a bucket.

        Args:
            bucket_name: Name of bucket

        Returns:
            Dict or None: Parsed policy or None if error
        """
        try:
            policy_str = self.client.get_bucket_policy(bucket_name)
            if policy_str:
                return json.loads(policy_str)
            return None
        except Exception as e:
            logger.error(f"Error getting bucket policy for {bucket_name}: {str(e)}")
            return None