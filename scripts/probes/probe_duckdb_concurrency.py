"""Check DuckDB's cross-process locking on this machine and version (no network).

A child process holds a read-write connection; the parent then tries to open
the same file read-only and read-write. Repeated after the writer closes, and
with two read-only connections from different processes at once.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import duckdb

from _common import OUT, record

DB = OUT / "concurrency.duckdb"

HOLDER = """
import sys, time, duckdb
mode = sys.argv[2]
con = duckdb.connect(sys.argv[1], read_only=(mode == "ro"))
print("ready", flush=True)
time.sleep(float(sys.argv[3]))
con.close()
"""


def try_open(label: str, read_only: bool) -> None:
    try:
        con = duckdb.connect(str(DB), read_only=read_only)
        rows = con.execute("select count(*) from t").fetchone()[0]
        if not read_only:
            con.execute("insert into t values (2)")
        con.close()
        record("duckdb_lock", case=label, read_only=read_only, ok=True, rows=rows)
    except Exception as exc:
        record("duckdb_lock", case=label, read_only=read_only, ok=False, error=f"{type(exc).__name__}: {exc}"[:300])


def with_holder(mode: str, label: str, attempts: list[bool]) -> None:
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(DB), mode, "6"], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "ready"
    for read_only in attempts:
        try_open(label, read_only)
    proc.wait()


def main() -> None:
    for suffix in ("", ".wal"):
        Path(str(DB) + suffix).unlink(missing_ok=True)
    con = duckdb.connect(str(DB))
    con.execute("create table t (x int)")
    con.execute("insert into t values (1)")
    con.close()
    record("duckdb_version", version=duckdb.__version__)

    with_holder("rw", "other process holds read-write", [True, False])
    try_open("no other process", True)
    with_holder("ro", "other process holds read-only", [True, False])


if __name__ == "__main__":
    main()
