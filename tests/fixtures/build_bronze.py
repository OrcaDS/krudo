"""Build the tiny CI bronze lake from `bronze_doe_prices.csv` (real bronze rows: RON 91 and
kerosene from six reports covering eras A, B, C, a stale effectivity date, a revised file,
the overlapping Makati/Caloocan label and DOE typos) and `bronze_manifest.csv`.

    uv run python tests/fixtures/build_bronze.py   # then LAKE_ROOT=tests/fixtures/parquet

The CSVs are the reviewable source; the Parquet they write is git-ignored.
"""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pv
import pyarrow.parquet as pq

from ingestion.common import manifest
from ingestion.doe.extract import SCHEMA

HERE = Path(__file__).parent
LAKE = HERE / "parquet"


def _read(csv_path: Path, schema: pa.Schema) -> pa.Table:
    return (
        pv.read_csv(
            csv_path,
            convert_options=pv.ConvertOptions(
                column_types=schema,
                strings_can_be_null=True,  # empty cell = NULL, quoted "" = empty string
                quoted_strings_can_be_null=False,
            ),
        )
        .select(schema.names)
        .cast(schema)
    )


def build(lake: Path = LAKE) -> int:
    """Write the fixture rows as bronze Parquet, one file per report. Returns rows written."""
    table = _read(HERE / "bronze_doe_prices.csv", SCHEMA)
    for source_file in pc.unique(table["source_file"]).to_pylist():
        part = table.filter(pc.equal(table["source_file"], source_file))
        year = part["report_date"][0].as_py().year
        out = lake / f"bronze/tables/doe_prices/year={year}/part-{Path(source_file).stem}.parquet"
        out.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(part, out, compression="snappy")
    pq.write_table(
        _read(HERE / "bronze_manifest.csv", manifest.SCHEMA), lake / "bronze/manifest.parquet"
    )
    return table.num_rows


if __name__ == "__main__":
    build()
