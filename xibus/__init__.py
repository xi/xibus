import contextlib

from .client import Client
from .connection import DBusError  # noqa
from .connection import get_connection


@contextlib.asynccontextmanager
async def get_client(bus):
    async with get_connection(bus) as con:
        yield Client(con)
