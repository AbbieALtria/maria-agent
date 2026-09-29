import uuid

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.crm.audit import audit, snapshot
from app.crm.deps import Admin, DbSession, Manager
from app.crm.enums import UserRole
from app.crm.models import Client, User
from app.crm.schemas import UserCreate, UserOut, UserUpdate
from app.crm.security import hash_password

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
async def list_users(session: DbSession, _: Manager) -> list[User]:
    return list(await session.scalars(select(User).order_by(User.email)))


async def _check_client(session: DbSession, client_id: uuid.UUID | None) -> None:
    if client_id is not None and await session.get(Client, client_id) is None:
        raise HTTPException(422, "client not found")


@router.post("", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, session: DbSession, actor: Admin) -> User:
    if await session.scalar(select(User.id).where(func.lower(User.email) == body.email)):
        raise HTTPException(status.HTTP_409_CONFLICT, "email already exists")
    await _check_client(session, body.client_id)
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        client_id=body.client_id,
    )
    session.add(user)
    await session.flush()
    audit(session, actor, "user.create", "user", user.id, after=snapshot(user))
    await session.commit()
    return user


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, session: DbSession, actor: Admin
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
    before = snapshot(user)
    changes = body.model_dump(exclude_unset=True)
    if "client_id" in changes:
        await _check_client(session, changes["client_id"])
    losing_admin = user.role == UserRole.admin and (
        changes.get("role", UserRole.admin) != UserRole.admin or changes.get("is_active") is False
    )
    if losing_admin:
        admins = await session.scalar(
            select(func.count()).where(User.role == UserRole.admin, User.is_active.is_(True))
        )
        if (admins or 0) <= 1:
            raise HTTPException(status.HTTP_409_CONFLICT, "cannot remove the last active admin")
    if "password" in changes:
        pw = changes.pop("password")
        if pw is not None:
            user.password_hash = hash_password(pw)
    for k, v in changes.items():
        if v is None and k in ("role", "is_active"):
            continue
        setattr(user, k, v)
    audit(session, actor, "user.update", "user", user.id, before=before, after=snapshot(user))
    await session.commit()
    await session.refresh(user)
    return user
