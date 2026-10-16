"""Labels, relationship types, constraints and indexes for the Lattice graph (KTD5, KTD6)."""

from lattice.graph.client import GraphClient

# Transaction data the agents investigate.
DATA_LABELS = ("Customer", "Account", "Device", "Alert")
# The system's own durable records; never part of a GDS projection.
APP_LABELS = ("Case", "LedgerEntry", "Action", "Recording")

OWNS = "OWNS"
TRANSFER = "TRANSFER"
USED_DEVICE = "USED_DEVICE"
DATA_REL_TYPES = (OWNS, TRANSFER, USED_DEVICE)

# Which data label an ID belongs to, from its prefix kind (see lattice.ids).
LABEL_BY_KIND = {"customer": "Customer", "account": "Account", "device": "Device", "alert": "Alert"}

_ID_KEYS = {label: "id" for label in DATA_LABELS + APP_LABELS} | {"LedgerEntry": "result_id"}

STATEMENTS = [
    *(
        f"CREATE CONSTRAINT {label.lower()}_{key} IF NOT EXISTS "
        f"FOR (n:{label}) REQUIRE n.{key} IS UNIQUE"
        for label, key in _ID_KEYS.items()
    ),
    f"CREATE CONSTRAINT transfer_id IF NOT EXISTS "
    f"FOR ()-[r:{TRANSFER}]-() REQUIRE r.id IS UNIQUE",
    f"CREATE INDEX transfer_ts IF NOT EXISTS FOR ()-[r:{TRANSFER}]-() ON (r.ts)",
    "CREATE INDEX case_status IF NOT EXISTS FOR (c:Case) ON (c.status)",
    # One open case per alert: active_key is the alert ID while open, null once closed.
    "CREATE CONSTRAINT case_active_key IF NOT EXISTS FOR (c:Case) REQUIRE c.active_key IS UNIQUE",
    "CREATE INDEX case_alert IF NOT EXISTS FOR (c:Case) ON (c.alert_id)",
    "CREATE INDEX action_case IF NOT EXISTS FOR (a:Action) ON (a.case_id)",
    "CREATE INDEX ledger_case IF NOT EXISTS FOR (l:LedgerEntry) ON (l.case_id)",
    # One recording per case, so concurrent saves update it instead of creating a second.
    "CREATE CONSTRAINT recording_case IF NOT EXISTS FOR (r:Recording) REQUIRE r.case_id IS UNIQUE",
    "CREATE INDEX recording_alert IF NOT EXISTS FOR (r:Recording) ON (r.alert_id)",
]


async def apply_schema(graph: GraphClient) -> None:
    """Create every constraint and index. Safe to run repeatedly."""
    for statement in STATEMENTS:
        await graph.write(statement)
    await graph.write("CALL db.awaitIndexes(60)")
