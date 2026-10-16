from pathlib import Path

import pytest

TESTS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items):
    """Mark tests by folder so `pytest -m unit` and `-m integration` select them."""
    for item in items:
        folder = Path(item.fspath).relative_to(TESTS_DIR).parts[0]
        if folder in ("unit", "integration"):
            item.add_marker(getattr(pytest.mark, folder))
