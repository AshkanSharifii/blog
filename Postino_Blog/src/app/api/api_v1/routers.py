# src/app/api/api_v1/routers.py
from fastapi import APIRouter
from src.app.api.api_v1.endpoints import auth, posts, tags, images

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(posts.router, prefix="/posts", tags=["posts"])
api_router.include_router(tags.router, prefix="/posts/tags", tags=["tags"])
api_router.include_router(images.router, prefix="/images", tags=["images"])