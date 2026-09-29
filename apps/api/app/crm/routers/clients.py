from fastapi import APIRouter
from sqlalchemy import select

from app.crm.deps import AnyUser, DbSession, Manager
from app.crm.models import Client
from app.crm.schemas import ClientIn, ClientOut

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientOut])
async def list_clients(session: DbSession, _: AnyUser) -> list[Client]:
    return list(await session.scalars(select(Client).order_by(Client.name)))


@router.post("", response_model=ClientOut, status_code=201)
async def create_client(body: ClientIn, session: DbSession, _: Manager) -> Client:
    client = Client(**body.model_dump())
    session.add(client)
    await session.commit()
    await session.refresh(client)
    return client
