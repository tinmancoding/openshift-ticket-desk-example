"""Short-lived connections keep this tiny demo simple; use pooling at production scale."""
import os

import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS tickets (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title VARCHAR(120) NOT NULL,
    description TEXT NOT NULL,
    priority VARCHAR(16) NOT NULL DEFAULT 'normal',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""
COLUMNS = "id, title, description, priority, created_at"


def connect():
    # Pass fields separately: passwords never become printable connection URLs.
    return psycopg.connect(host=os.environ["DB_HOST"], port=int(os.environ.get("DB_PORT", "5432")),
                           dbname=os.environ["DB_NAME"], user=os.environ["DB_USER"],
                           password=os.environ["DB_PASSWORD"], connect_timeout=3,
                           row_factory=dict_row, options="-c statement_timeout=5000")


def serialize(row):
    if row is None:
        return None
    result = dict(row)
    result["created_at"] = result["created_at"].isoformat()
    return result


class PostgresRepository:
    def ready(self):
        with connect() as connection:
            connection.execute("SELECT id FROM tickets LIMIT 1")

    def create(self, title, description, priority):
        with connect() as connection:
            row = connection.execute(
                f"INSERT INTO tickets (title, description, priority) VALUES (%s, %s, %s) RETURNING {COLUMNS}",
                (title, description, priority)).fetchone()
            return serialize(row)

    def get(self, ticket_id):
        with connect() as connection:
            return serialize(connection.execute(
                f"SELECT {COLUMNS} FROM tickets WHERE id = %s", (ticket_id,)).fetchone())

    def list_recent(self):
        with connect() as connection:
            return [serialize(row) for row in connection.execute(
                f"SELECT {COLUMNS} FROM tickets ORDER BY id DESC LIMIT 50").fetchall()]


def migrate():
    with connect() as connection:
        connection.execute(SCHEMA)
    print("Ticket schema initialized (idempotent initial schema only).")


if __name__ == "__main__":
    migrate()
