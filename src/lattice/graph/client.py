"""The single async Neo4j wrapper every Lattice module uses."""

from typing import Any, Self

from neo4j import (
    READ_ACCESS,
    AsyncDriver,
    AsyncGraphDatabase,
    AsyncManagedTransaction,
    Record,
    RoutingControl,
    unit_of_work,
)

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

    async def query_type(self, query: str, **params: Any) -> str:
        """How Neo4j classifies a query without running it: 'r', 'rw', 'w' or 's'."""
        return (await self.explain(query, **params))[0]

    async def explain(self, query: str, **params: Any) -> tuple[str, list[str]]:
        """The query type and every plan operator as "Operator details", without running it."""
        result = await self._driver.execute_query(
            f"EXPLAIN {query}", parameters_=params, routing_=RoutingControl.READ
        )
        operators: list[str] = []

        def walk(plan: dict[str, Any]) -> None:
            operators.append(f"{plan.get('operatorType', '')} "
                             f"{plan.get('args', {}).get('Details', '')}")
            for child in plan.get("children", []):
                walk(child)

        if result.summary.plan:
            walk(result.summary.plan)
        return result.summary.query_type, operators

    async def read_records(
        self, query: str, params: dict[str, Any], *, timeout: float, max_rows: int
    ) -> tuple[list[Record], bool]:
        """Run inside a read transaction with a timeout; return at most `max_rows` records."""

        @unit_of_work(timeout=timeout)
        async def work(tx: AsyncManagedTransaction) -> tuple[list[Record], bool]:
            result = await tx.run(query, params)
            records: list[Record] = []
            async for record in result:
                if len(records) == max_rows:
                    return records, True
                records.append(record)
            return records, False

        async with self._driver.session(default_access_mode=READ_ACCESS) as session:
            return await session.execute_read(work)

    async def close(self) -> None:
        await self._driver.close()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
