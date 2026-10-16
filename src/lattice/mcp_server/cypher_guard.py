"""Static checks for the read-only Cypher fallback tool.

This is the first of three guards. `graph_cypher_readonly` also requires `EXPLAIN` to classify
the query as read-only and runs it in a read transaction, so a write that slips past these
patterns is still refused by the database.
"""

import re

WRITE_CLAUSES = (
    "LOAD CSV",
    "CREATE",
    "MERGE",
    "DELETE",
    "SET",
    "REMOVE",
    "DROP",
    "FOREACH",
    "DETACH",
    "TRANSACTIONS",
)
ALLOWED_PROCEDURES = frozenset(
    {"db.labels", "db.relationshipTypes", "db.propertyKeys", "db.schema.visualization"}
)

_STRINGS_AND_COMMENTS = re.compile(
    r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|//[^\n]*|/\*.*?\*/", re.DOTALL
)
_PROCEDURE_CALL = re.compile(r"\bCALL\s+([A-Za-z_][\w.]*)\s*\(", re.IGNORECASE)


class CypherRejected(ValueError):
    """The query is not a single read-only statement."""


def check_readonly(query: str) -> None:
    code = _STRINGS_AND_COMMENTS.sub(" ", query)

    if ";" in code.strip().rstrip(";"):
        raise CypherRejected("only a single statement is allowed")

    for match in _PROCEDURE_CALL.finditer(code):
        procedure = match.group(1)
        if procedure not in ALLOWED_PROCEDURES:
            raise CypherRejected(f"procedure {procedure} is not on the read-only allow-list")

    for clause in WRITE_CLAUSES:
        # Not preceded by a dot, so property and procedure names like n.set or apoc.create pass.
        pattern = r"(?<![.\w])" + r"\s+".join(clause.split()) + r"\b"
        if re.search(pattern, code, re.IGNORECASE):
            raise CypherRejected(f"{clause} is not allowed in read-only queries")
