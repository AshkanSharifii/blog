# src/app/schemas/post_schema.py
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, field_validator, model_validator
import re


# ------------------- Post Schemas -------------------

class PostBase(BaseModel):
    """
    Base schema for post data that's common across create and update operations.
    """
    title: str = Field(default="", description="Post title")
    content: str = Field(default="", description="Post content in markdown format")
    # UI sends comma‑separated names, e.g. "هواوی,انویدیا"
    tags: Optional[str] = Field(
        default=None,
        description="Comma‑separated tag names sent by the form"
    )
    is_active: Optional[bool] = Field(
        default=True,
        description="Whether the post is active and visible to users"
    )
    is_archived: Optional[bool] = Field(
        default=False,
        description="Whether the post is archived"
    )

    @field_validator('title')
    @classmethod
    def title_not_empty(cls, v):
        # Allow empty title, but strip whitespace
        return v.strip() if v else v

    @field_validator('content')
    @classmethod
    def content_not_empty(cls, v):
        # Allow empty content, but strip whitespace
        return v.strip() if v else v

    @field_validator('tags')
    @classmethod
    def validate_tags(cls, v):
        if v is None:
            return v

        # Strip whitespace from tags
        tags = [tag.strip() for tag in v.split(',')]

        # Filter out empty tags
        tags = [tag for tag in tags if tag]

        # Rejoin with commas
        return ','.join(tags) if tags else None


class PostCreate(PostBase):
    """
    Schema for creating a new post.
    """
    # Additional fields specific to post creation
    notify_subscribers: bool = Field(
        default=False,
        description="Whether to notify subscribers about this post"
    )

    publish_immediately: bool = Field(
        default=True,
        description="Whether to publish the post immediately or save as draft"
    )

    @model_validator(mode='after')
    def validate_post_creation(self):
        # Add any cross-field validation logic here
        return self


class PostUpdate(PostBase):
    """
    Schema for updating an existing post.
    """
    # Options for image management
    delete_unused_images: bool = Field(
        default=False,
        description="If True, will delete images that are no longer used in content"
    )

    keep_cover_image: bool = Field(
        default=True,
        description="If True and no new cover image is provided, keeps the existing one"
    )

    update_timestamp: bool = Field(
        default=True,
        description="Whether to update the post's updated_at timestamp"
    )

    @model_validator(mode='after')
    def validate_post_update(self):
        # Add any cross-field validation logic here
        return self


class PostOut(BaseModel):
    """
    Schema for returning a post in API responses.
    """
    id: int = Field(..., description="Post ID")
    title: str = Field(default="", description="Post title")
    content: str = Field(default="", description="Post content in markdown format")
    image_url: Optional[str] = Field(
        default=None,
        description="URL or filename of the cover image"
    )

    # Tag names array
    tags: List[str] = Field(
        default=[],
        example=["هواوی", "انویدیا"],
        description="List of tag names attached to the post"
    )

    created_at: datetime = Field(..., description="Post creation timestamp")
    updated_at: Optional[datetime] = Field(
        default=None,
        description="Last update timestamp (null if never updated)"
    )

    # Added new fields
    is_active: bool = Field(
        default=True,
        description="Whether the post is active and visible to users"
    )
    is_archived: bool = Field(
        default=False,
        description="Whether the post is archived"
    )

    # ↓ If you track the author of each post
    author: Optional[str] = Field(
        default=None,
        description="Username of the post author"
    )

    # ↓ If you track the status of posts (published, draft, etc.)
    status: str = Field(
        default="published",
        description="Post status: published, draft, archived"
    )

    # ↓ If you count views or comments
    view_count: Optional[int] = Field(
        default=0,
        description="Number of views"
    )

    comment_count: Optional[int] = Field(
        default=0,
        description="Number of comments"
    )

    # Methods to extract metadata from posts
    def has_cover_image(self) -> bool:
        """Check if post has a cover image."""
        return self.image_url is not None and len(self.image_url) > 0

    def extract_content_images(self) -> List[str]:
        """Extract image URLs from post content."""
        pattern = r'!\[.*?\]\(([^)]+)\)'
        return re.findall(pattern, self.content)

    def get_summary(self, max_length: int = 150) -> str:
        """Generate a summary from post content."""
        # Strip markdown and HTML tags
        text = re.sub(r'!\[.*?\]\([^)]+\)', '', self.content)  # Remove images
        text = re.sub(r'(\*\*|__)(.*?)\1', r'\2', text)  # Remove bold
        text = re.sub(r'(\*|_)(.*?)\1', r'\2', text)  # Remove italic
        text = re.sub(r'#{1,6}\s+', '', text)  # Remove headings
        text = re.sub(r'<[^>]*>', '', text)  # Remove HTML

        # Limit to max_length
        if len(text) > max_length:
            return text[:max_length].rstrip() + '...'
        return text.strip()

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            datetime: lambda dt: dt.isoformat()
        }
    }


class PostListItem(BaseModel):
    """
    Schema for returning a post in list views (with less detail).
    """
    id: int
    title: str
    image_url: Optional[str] = None
    tags: List[str] = []
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True
    is_archived: bool = False
    status: str = "published"
    summary: str = Field(
        default="",
        description="Auto-generated summary of the post content"
    )

    model_config = {
        "from_attributes": True
    }

    @classmethod
    def from_post(cls, post: PostOut) -> 'PostListItem':
        """Create a PostListItem from a PostOut."""
        return cls(
            id=post.id,
            title=post.title,
            image_url=post.image_url,
            tags=post.tags,
            created_at=post.created_at,
            updated_at=post.updated_at,
            is_active=post.is_active,
            is_archived=post.is_archived,
            status=post.status,
            summary=post.get_summary(150)
        )


# ------------------- Post Pagination Schemas -------------------

class PostPagination(BaseModel):
    """
    Schema for paginated post responses.
    Matches the Angular frontend's expected structure.
    """
    items: List[PostOut]
    total: int = Field(..., description="Total number of posts")
    page: int = Field(..., description="Current page number (1-based)")
    page_size: int = Field(..., description="Number of items per page")
    total_pages: int = Field(..., description="Total number of pages")
    start_item: int = Field(..., description="Number of the first item on the current page")
    end_item: int = Field(..., description="Number of the last item on the current page")
    has_more: bool = Field(..., description="Whether there are more pages after this one")

    model_config = {
        "from_attributes": True,
        "json_encoders": {
            datetime: lambda dt: dt.isoformat()
        }
    }


# ------------------- Post Filter Schemas -------------------

class PostFilter(BaseModel):
    """
    Schema for filtering posts in list endpoints.
    """
    search: Optional[str] = Field(
        default=None,
        description="Search term to filter posts by title or content"
    )

    tags: Optional[List[str]] = Field(
        default=None,
        description="List of tag names to filter posts"
    )

    author: Optional[str] = Field(
        default=None,
        description="Filter posts by author username"
    )

    status: Optional[str] = Field(
        default=None,
        description="Filter posts by status: published, draft, archived"
    )

    is_active: Optional[bool] = Field(
        default=None,
        description="Filter posts by active status"
    )

    is_archived: Optional[bool] = Field(
        default=None,
        description="Filter posts by archive status"
    )

    from_date: Optional[datetime] = Field(
        default=None,
        description="Filter posts created after this date"
    )

    to_date: Optional[datetime] = Field(
        default=None,
        description="Filter posts created before this date"
    )


# ------------------- Post Stats Schemas -------------------

class PostStats(BaseModel):
    """
    Schema for post statistics.
    """
    total_posts: int = Field(..., description="Total number of posts")
    total_views: int = Field(..., description="Total number of post views")
    total_comments: int = Field(..., description="Total number of comments")
    active_posts: int = Field(..., description="Number of active posts")
    archived_posts: int = Field(..., description="Number of archived posts")
    posts_by_tag: Dict[str, int] = Field(
        default_factory=dict,
        description="Number of posts by tag"
    )
    posts_by_month: Dict[str, int] = Field(
        default_factory=dict,
        description="Number of posts by month"
    )