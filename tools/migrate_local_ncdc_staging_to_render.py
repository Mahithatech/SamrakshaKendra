#!/usr/bin/env python3
"""Safely copy local NCDC candidate rows to Render's separate staging table.

This utility never writes to idsp_surveillance. It fails before connecting if
an incomplete or malformed URL is entered, checks schemas/row counts, refuses
non-empty destinations, and uses a single transaction for staging insertion.
"""
from __future__ import annotations

import getpass
import sys
from pathlib import Path
from typing import Any

from dotenv import dotenv_values
from sqlalchemy import MetaData, create_engine, inspect, select, func
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = ROOT / "backend" / ".env"
TABLE = "ncdc_outbreak_staging"


def _normalise_local_url(raw: str) -> URL:
    """Normalize local PostgreSQL driver without disclosing credentials."""
    url = make_url(raw.strip())
    if url.drivername == "postgres":
        url = url.set(drivername="postgresql+psycopg")
    elif url.drivername == "postgresql":
        url = url.set(drivername="postgresql+psycopg")
    return url


def parse_external_url(raw: str) -> URL:
    """Validate a pasted Render external URL; never echo it in error output."""
    value = (raw or "").strip()
    if not value:
        raise ValueError("No URL entered.")
    if not value.startswith(("postgres://", "postgresql://", "postgresql+psycopg://")):
        raise ValueError("This is not a PostgreSQL connection URL. Copy Render's External Database URL.")
    try:
        url = make_url(value)
    except Exception as exc:
        raise ValueError("The connection URL could not be parsed; copy the complete URL again.") from exc
    if url.drivername in {"postgres", "postgresql"}:
        url = url.set(drivername="postgresql+psycopg")
    if url.drivername != "postgresql+psycopg":
        raise ValueError("Use a PostgreSQL URL supported by the installed Psycopg 3 driver.")
    if not url.host or not url.username or not url.password or not url.database:
        raise ValueError("The URL must include host, username, password and database name.")
    if "://" in url.database or "postgresql:" in url.database.lower():
        raise ValueError("The URL looks concatenated or malformed. Copy just the full External Database URL.")
    if "://" in url.host:
        raise ValueError("The hostname in the URL is malformed.")
    query = dict(url.query)
    # Render external Postgres endpoints require TLS. Preserve existing settings.
    query.setdefault("sslmode", "require")
    return url.set(query=query)


def _count(engine, table) -> int:
    with engine.connect() as connection:
        return int(connection.execute(select(func.count()).select_from(table)).scalar_one())


def main() -> int:
    local_url_raw = dotenv_values(LOCAL_ENV).get("DATABASE_URL")
    if not local_url_raw:
        print("STOP: local DATABASE_URL was not found in backend/.env.", file=sys.stderr)
        return 2

    print("This copies candidate rows into public.ncdc_outbreak_staging only.")
    print("It never modifies idsp_surveillance and never promotes records.")
    print("Use the NEW Render external URL after rotating the exposed credential.")
    raw = getpass.getpass("Paste the NEW Render EXTERNAL Database URL (hidden): ").strip()
    try:
        local_url = _normalise_local_url(local_url_raw)
        remote_url = parse_external_url(raw)
    except ValueError as exc:
        print(f"STOP: {exc}", file=sys.stderr)
        return 2

    if local_url.host == remote_url.host and local_url.database == remote_url.database and local_url.username == remote_url.username:
        print("STOP: source and destination appear to be the same database.", file=sys.stderr)
        return 2

    source = create_engine(local_url, pool_pre_ping=True)
    target = create_engine(remote_url, pool_pre_ping=True, connect_args={"connect_timeout": 15})
    try:
        src_names = set(inspect(source).get_table_names(schema="public"))
        dst_names = set(inspect(target).get_table_names(schema="public"))
        if TABLE not in src_names or TABLE not in dst_names:
            print("STOP: local and hosted public.ncdc_outbreak_staging tables must both exist.", file=sys.stderr)
            return 2

        source_meta, target_meta = MetaData(), MetaData()
        source_meta.reflect(bind=source, schema="public", only=[TABLE])
        target_meta.reflect(bind=target, schema="public", only=[TABLE])
        src_table = source_meta.tables[f"public.{TABLE}"]
        dst_table = target_meta.tables[f"public.{TABLE}"]
        source_columns = set(src_table.c.keys())
        destination_columns = set(dst_table.c.keys())
        common = [column.name for column in src_table.columns if column.name in destination_columns]
        target_column_info = inspect(target).get_columns(TABLE, schema="public")
        missing_required = sorted(
            column["name"] for column in target_column_info
            if not column.get("nullable", True)
            and column.get("default") is None
            and column.get("identity") is None
            and column["name"] not in source_columns
        )
        if missing_required:
            print("STOP: hosted staging schema requires unavailable local columns: " + ", ".join(missing_required), file=sys.stderr)
            return 2
        if "record_id" not in common:
            print("STOP: record_id is not shared by both staging schemas.", file=sys.stderr)
            return 2

        source_count, destination_count = _count(source, src_table), _count(target, dst_table)
        print(f"Local candidate rows: {source_count}")
        print(f"Hosted staging rows before: {destination_count}")
        print(f"Shared columns: {len(common)}")
        if source_count == 0:
            print("Nothing to copy: local staging is empty.")
            return 0
        if destination_count != 0:
            print("STOP: hosted staging is not empty; no rows copied. Review IDs before retrying.", file=sys.stderr)
            return 2

        copied = 0
        with source.connect() as src_conn, target.begin() as dst_conn:
            result = src_conn.execute(select(*(src_table.c[name] for name in common)))
            while True:
                batch = result.fetchmany(500)
                if not batch:
                    break
                records: list[dict[str, Any]] = [
                    {name: row._mapping[name] for name in common}
                    for row in batch
                ]
                dst_conn.execute(dst_table.insert(), records)
                copied += len(records)

        final_count = _count(target, dst_table)
        print(f"Copied to hosted staging only: {copied}")
        print(f"Hosted staging rows after: {final_count}")
        print("Safety: live IDSP surveillance totals were not changed.")
        return 0 if copied == source_count and final_count == source_count else 1
    except Exception as exc:
        # Avoid exception details because some driver errors can include URL data.
        print(f"Migration stopped safely: {type(exc).__name__}.", file=sys.stderr)
        print("No live records were promoted. Check credential, TLS, URL format and database access rules.", file=sys.stderr)
        return 1
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
