"""Static checks for the read-only Cypher fallback tool.

This is the first of three guards. `graph_cypher_readonly` also requires `EXPLAIN` to classify
the query as read-only and runs it in a read transaction, so a write that slips past these
patterns is still refused by the database.

`check_plan` keeps the system's own records (cases, actions, ledger, recordings) out of reach.
It reads the query plan rather than the text, so spelling a label differently (`labels(n)`,
backticks, whitespace) cannot get round it: a query may not scan every node, look nodes up by
internal ID, or touch an application label. Application records have no relationships, so
expanding from data nodes never reaches them.
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


APP_LABEL_IN_PLAN = re.compile(r"[:|&]\s*`?(Case|LedgerEntry|Action|Recording)`?\b")
WHOLE_GRAPH_OPERATORS = ("AllNodesScan", "NodeByIdSeek", "NodeByElementIdSeek")


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


def check_plan(operators: list[str]) -> None:
    """Refuse plans that could reach application records (see the module docstring)."""
    for operator in operators:
        name = operator.split(" ", 1)[0].split("@", 1)[0]
        if name in WHOLE_GRAPH_OPERATORS:
            raise CypherRejected("start from a labelled data node (Account, Customer, Device or "
                                 "Alert); scanning every node is not allowed")
        match = APP_LABEL_IN_PLAN.search(operator)
        if match:
            raise CypherRejected(f"{match.group(1)} records are not readable through this tool")
