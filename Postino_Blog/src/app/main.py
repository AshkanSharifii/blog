from fastapi import FastAPI

from src.app.database.database import engine, Base, SessionLocal
from src.app.core.config import settings
from src.app.crud.user_crud import get_user_by_username, create_user
from src.app.schemas.user_schema import UserCreate
from src.app.api.api_v1.routers import api_router

from fastapi.middleware.cors import CORSMiddleware

# --- Use the new MinIO client with blog_bucket -------------
from src.app.services.minio_client import MinioClient

# Initialize MinIO client with all buckets
minio_client = MinioClient(
    url=settings.minio_endpoint,         # minio:9000
    access_key=settings.minio_root_user,
    secret_key=settings.minio_root_password,
    blog_bucket=settings.minio_bucket,   # "posts"
)
# -------------------------------------------------------------------------

app = FastAPI()

# Updated origins list to include Angular dev server
origins = [
    "http://localhost:4200",  # Angular dev server
    "http://localhost:8000",  # FastAPI server
    "http://localhost",       # For other local development
    "http://127.0.0.1:4200",  # Alternative Angular URL
    "http://127.0.0.1:8000",  # Alternative FastAPI URL
    "*"                       # Keep wildcard during development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],     # Expose headers to the client
    max_age=600               # Cache preflight requests for 10 minutes
)

# 1. tables
Base.metadata.create_all(bind=engine)

# 2. default user
def init_default_user() -> None:
    db = SessionLocal()
    try:
        email = settings.default_user_email
        if not get_user_by_username(db, email):
            user_in = UserCreate(
                username=email,
                email=email,
                password=settings.default_user_password,
            )
            create_user(db, user_in)
            print(f"✨ Created default user {email}")
    finally:
        db.close()

@app.on_event("startup")
def on_startup() -> None:
    init_default_user()

# 3. mount api
app.include_router(api_router, prefix="/api/v1")