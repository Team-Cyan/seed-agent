import re
import sqlite3
from pathlib import Path

from seed_agent.state import StateStore

DOC_PATH = Path("docs/operations/config-and-state-fields.md")


def test_sqlite_state_inventory_documents_current_schema(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    documented = _documented_sqlite_tables(DOC_PATH)

    with sqlite3.connect(store.path) as conn:
        actual_tables = {
            row[0]
            for row in conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                """
            )
        }
        actual_columns = {
            table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
            for table in actual_tables
        }

    assert set(documented) == actual_tables
    for table, documented_columns in documented.items():
        assert set(documented_columns) == actual_columns[table]


def _documented_sqlite_tables(path: Path) -> dict[str, list[str]]:
    content = path.read_text(encoding="utf-8")
    _, sqlite_section = content.split("## SQLite Tables", maxsplit=1)
    tables: dict[str, list[str]] = {}
    current_table: str | None = None

    for line in sqlite_section.splitlines():
        table_match = re.fullmatch(r"`([^`]+)`", line)
        if table_match:
            current_table = table_match.group(1)
            tables[current_table] = []
            continue
        column_match = re.fullmatch(r"- `([^`]+)`", line)
        if column_match and current_table is not None:
            tables[current_table].append(column_match.group(1))

    return tables
