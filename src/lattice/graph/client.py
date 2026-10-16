"""The single async Neo4j wrapper every Lattice module uses."""

from typing import Any, Self

from neo4j import AsyncDriver, AsyncGraphDatabase, RoutingControl

from lattice.config import Settings


class GraphClient:
    def __init__(self, driver: AsyncDriver) -> None:
        self._driver = driver

    @classmethod
    def from_settings(cls, settings: Settings) -> Self:
        auth = (settings.neo4j_user, settings.neo4j_password.get_secret_value())
        return cls(AsyncGraphDatabase.driver(settings.neo4j_uri, auth=auth))

    async def read(self, query: str, **params: Any) -> list[dict[str, Any]]:
        return await self._run(query, params, RoutingControl.READ)

    async def write(self, query: str, **params: Any) -> list[dict[str, Any]]:
        return await self._run(query, params, RoutingControl.WRITE)

    async def _run(
        self, query: str, params: dict[str, Any], routing: RoutingControl
    ) -> list[dict[str, Any]]:
        result = await self._driver.execute_query(query, parameters_=params, routing_=routing)
        return [record.data() for record in result.records]

    async def close(self) -> None:
        await self._driver.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
