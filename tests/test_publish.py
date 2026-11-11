"""Tests for exporting gold and deciding whether to publish (no GitHub calls)."""

import zipfile

import duckdb

from warehouse import publish


def _exports(tmp_path):
    db = tmp_path / "t.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE a AS SELECT * FROM range(3) t(i)")
        con.execute("CREATE TABLE b AS SELECT 'x' AS s")
    return publish.export_gold(db, tmp_path / "gold", ["a", "b"])


def test_gold_tables_are_the_gold_models():
    tables = publish.gold_tables()
    assert "fct_pump_prices" in tables and "fct_ncr_summary" in tables and "dim_city" in tables
    assert not any(t.startswith("stg_") for t in tables)


def test_export_hash_is_stable_and_follows_the_data(tmp_path):
    db = tmp_path / "t.duckdb"
    with duckdb.connect(str(db)) as con:
        con.execute("CREATE TABLE g AS SELECT * FROM range(1000) t(i) ORDER BY random()")
    first = publish.export_gold(db, tmp_path / "a", ["g"])[0]
    with duckdb.connect(str(db)) as con:  # same rows, different physical order
        con.execute("CREATE OR REPLACE TABLE g AS SELECT * FROM g ORDER BY random()")
    assert publish.export_gold(db, tmp_path / "b", ["g"])[0].sha256 == first.sha256
    assert first.rows == 1000
    with duckdb.connect(str(db)) as con:
        con.execute("INSERT INTO g VALUES (1000)")
    assert publish.export_gold(db, tmp_path / "c", ["g"])[0].sha256 != first.sha256


def test_export_works_while_dbt_holds_the_database(tmp_path):
    db = tmp_path / "t.duckdb"
    with duckdb.connect(str(db)) as held:  # as dbt's connection stays open within run-all
        held.execute("CREATE TABLE g AS SELECT 1 AS i")
        assert publish.export_gold(db, tmp_path / "out", ["g"])[0].rows == 1


def test_changed_only_when_a_table_differs_from_the_latest_release(tmp_path):
    exports = _exports(tmp_path)
    same = {f"{e.table}.parquet": e.sha256 for e in exports}
    assert not publish.changed(exports, same)
    assert publish.changed(exports, {**same, "a.parquet": "other"})
    assert publish.changed(exports, {"a.parquet": same["a.parquet"]})  # b is new
    assert publish.changed(exports, {})  # no release yet


def test_csv_zip_holds_every_table_with_a_header(tmp_path):
    out = publish.csv_zip(_exports(tmp_path), tmp_path / publish.CSV_ZIP)
    with zipfile.ZipFile(out) as zf:
        assert sorted(zf.namelist()) == ["a.csv", "b.csv"]
        assert zf.read("a.csv").decode().splitlines() == ["i", "0", "1", "2"]
    assert not list(tmp_path.glob("*.csv"))  # temporary CSVs are removed
