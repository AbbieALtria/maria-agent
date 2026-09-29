from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.crm.deps import CurrentUser, DbSession
from app.crm.models import User
from app.crm.schemas import LoginIn, TokenOut, UserOut
from app.crm.security import create_access_token, verify_password

router = APIRouter(tags=["auth"])


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, session: DbSession) -> TokenOut:
    user = await session.scalar(select(User).where(func.lower(User.email) == body.email))
    ok = verify_password(body.password, user.password_hash if user else None)
    if not user or not ok or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid email or password")
    return TokenOut(
        token=create_access_token(user.id, user.role.value), user=UserOut.model_validate(user)
    )


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
