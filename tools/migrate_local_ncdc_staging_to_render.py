#!/usr/bin/env python3
"""Copy local NCDC candidates to the hosted staging table only.

This never writes to idsp_surveillance or any live totals. It refuses to copy if
the hosted staging table is non-empty or required columns cannot be preserved.
The hosted database URL is requested interactively and never printed.
"""
from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from dotenv import dotenv_values
from sqlalchemy import MetaData, create_engine, inspect, select, func

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = ROOT / "backend" / ".env"
TABLE = "ncdc_outbreak_staging"


def normalize_url(url: str) -> str:
    url = url.strip()
    if url.startswith("postgres://"):
        return "postgresql+psycopg://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def main() -> int:
    local_url = dotenv_values(LOCAL_ENV).get("DATABASE_URL")
    if not local_url:
        print("STOP: DATABASE_URL was not found in backend/.env", file=sys.stderr)
        return 2

    remote_url = getpass.getpass("Render EXTERNAL Database URL (hidden): ").strip()
    if not remote_url:
        print("STOP: no Render URL entered.", file=sys.stderr)
        return 2
    if remote_url.strip().lower() == local_url.strip().lower():
        print("STOP: source and destination URLs match.", file=sys.stderr)
        return 2

    source = create_engine(normalize_url(local_url), pool_pre_ping=True)
    target = create_engine(normalize_url(remote_url), pool_pre_ping=True,
                           connect_args={"connect_timeout": 15})
    try:
        src_inspector = inspect(source)
        dst_inspector = inspect(target)
        src_tables = set(src_inspector.get_table_names(schema="public"))
        dst_tables = set(dst_inspector.get_table_names(schema="public"))
        if TABLE not in src_tables or TABLE not in dst_tables:
            print("STOP: local and hosted public.ncdc_outbreak_staging tables must both exist.", file=sys.stderr)
            return 2

        source_meta = MetaData()
        target_meta = MetaData()
        source_meta.reflect(bind=source, schema="public", only=[TABLE])
        target_meta.reflect(bind=target, schema="public", only=[TABLE])
        src_table = source_meta.tables[f"public.{TABLE}"]
        dst_table = target_meta.tables[f"public.{TABLE}"]
        src_columns = set(src_table.c.keys())
        dst_columns = set(dst_table.c.keys())
        common = [column.name for column in src_table.columns if column.name in dst_columns]

        # Every destination non-null column without a server default must be supplied.
        target_columns = {c["name"]: c for c in dst_inspector.get_columns(TABLE, schema="public")}
        missing_required = sorted(
            name for name, col in target_columns.items()
            if not col.get("nullable", True)
            and col.get("default") is None
            and col.get("identity") is None
            and name not in src_columns
        )
        if missing_required:
            print("STOP: destination requires columns not available locally: " + ", ".join(missing_required), file=sys.stderr)
            return 2

        with source.connect() as conn:
            source_count = int(conn.execute(select(func.count()).select_from(src_table)).scalar_one())
        with target.connect() as conn:
            target_count = int(conn.execute(select(func.count()).select_from(dst_table)).scalar_one())
        print(f"Local staging rows: {source_count}")
        print(f"Render staging rows before: {target_count}")
        print(f"Shared columns copied: {len(common)}")

        if source_count == 0:
            print("Nothing to copy; local staging table is empty.")
            return 0
        if target_count != 0:
            print("STOP: hosted staging table is not empty. No rows copied; review existing IDs first.", file=sys.stderr)
            return 2
        if "record_id" not in common:
            print("STOP: staging record_id is missing from the shared schema.", file=sys.stderr)
            return 2

        copied = 0
        with source.connect() as source_conn, target.begin() as target_conn:
            result = source_conn.execute(select(*(src_table.c[name] for name in common)))
            target_columns_order = [name for name in common if name in dst_columns]
            while True:
                batch = result.fetchmany(500)
                if not batch:
                    break
                records = [{name: row._mapping[name] for name in target_columns_order} for row in batch]
                target_conn.execute(dst_table.insert(), records)
                copied += len(records)

        with target.connect() as conn:
            final_count = int(conn.execute(select(func.count()).select_from(dst_table)).scalar_one())
        print(f"Copied to hosted staging only: {copied}")
        print(f"Render staging rows after: {final_count}")
        print("Safety: idsp_surveillance and live dashboard totals were not modified by this script.")
        return 0 if copied == source_count and final_count == source_count else 1
    except Exception as exc:
        print(f"Migration stopped safely: {type(exc).__name__}: {str(exc)[:400]}", file=sys.stderr)
        return 1
    finally:
        source.dispose()
        target.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
