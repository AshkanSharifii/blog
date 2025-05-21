# src/app/api/api_v1/dependencies.py

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from src.app.database.database import get_db
from src.app.crud.user_crud import get_user_by_username
from src.app.core.security import decode_access_token
from src.app.models.user_model import User

# This tells FastAPI / OpenAPI that we have an OAuth2 Bearer flow,
# with tokenUrl matching our login endpoint.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Dependency that:
      1) Reads an OAuth2 Bearer token from the Authorization header
      2) Decodes + validates it
      3) Loads the User from the database
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = get_user_by_username(db, username)
    if user is None:
        raise credentials_exception
    return user
