"""Keep the lake in a GitHub Release, so a fresh machine or a CI run can restore it.

The pipeline always works on a local lake. ``push`` packs it into release assets and
``pull`` unpacks them:

- ``bronze.tar``: bronze tables and the manifest (all a weekly run needs, ~5 MB).
- ``pdfs-YYYY.tar``: the original DOE PDFs of one listing year (~10 MB each).

Tars are deterministic (sorted, fixed metadata), so an unchanged year has the same
sha256 as the asset GitHub already holds and is not uploaded again. A year whose PDFs
are only partly on this machine (a CI run that downloaded this week's report) is
completed from its asset first. Every PDF is checked against its manifest hash before upload, so
a push can never replace an archive with a smaller or corrupted one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Protocol

import pyarrow.parquet as pq

from ingestion.common.manifest import MANIFEST_PATH

logger = logging.getLogger(__name__)

TAG = "lake"  # one release holds every asset; never marked "latest" (that is the open data)
BRONZE_ASSET = "bronze.tar"
# Path prefixes bronze.tar may hold (the manifest is a single file)
BRONZE_PREFIXES = ("bronze/tables/", MANIFEST_PATH)
PDF_PREFIXES = ("bronze/files/",)
_YEAR = re.compile(r"/year=(\d{4})/")
RELEASE_NOTES = """\
Pipeline state for krudo, restored with `krudo lake-pull`. **For the cleaned, standardized \
pump price data, use the latest release instead.**

- `bronze.tar`: prices as extracted from the reports (raw text) and the file manifest.
- `pdfs-YYYY.tar`: unmodified copies of the Department of Energy's NCR retail pump price \
monitoring reports listed under that year, as published at \
https://doe.gov.ph/data-and-prices/liquid-fuels/retail-pump-prices/ncr-pump-prices.

Source: Department of Energy - Oil Industry Management Bureau (Philippines). This is not an \
official DOE source; DOE's own site is authoritative.
"""


class Release(Protocol):
    """The release operations push and pull need (GitHub via ``gh``; a folder in tests)."""

    def assets(self) -> dict[str, str]:
        """Asset name -> sha256 hex digest; empty if the release does not exist."""
        ...

    def download(self, name: str, dest: Path) -> Path: ...

    def upload(self, path: Path) -> None: ...


class GhRelease:
    """The ``lake`` release of the current repo, through the GitHub CLI.

    The repo comes from the git remote, or from ``GH_REPO`` where there is no checkout.
    shortcut: needs the ``gh`` binary (preinstalled on GitHub runners, not in the image);
    switch to the REST API if the container must push itself.
    """

    def __init__(self, tag: str = TAG) -> None:
        if shutil.which("gh") is None:
            raise RuntimeError("The GitHub CLI 'gh' is not installed or not on PATH")
        self.tag = tag
        self._exists = False

    def _gh(self, *args: str) -> str:
        try:
            return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout
        except subprocess.CalledProcessError as exc:
            exc.add_note(f"gh stderr: {exc.stderr.strip()}")  # shown in the traceback
            raise

    def assets(self) -> dict[str, str]:
        try:
            out = self._gh("api", f"repos/{{owner}}/{{repo}}/releases/tags/{self.tag}")
        except subprocess.CalledProcessError as exc:
            if "404" in exc.stderr:
                return {}
            raise
        return {
            a["name"]: (a.get("digest") or "").removeprefix("sha256:")
            for a in json.loads(out)["assets"]
        }

    def _transfer(self, *args: str) -> None:
        """Run an upload or download, retrying: large transfers sometimes drop mid-way."""
        for wait in (10, 60, None):
            try:
                self._gh("release", *args, "--clobber")
                return
            except subprocess.CalledProcessError:
                if wait is None:
                    raise
                logger.warning("gh release %s failed; retrying in %d s", args[0], wait)
                time.sleep(wait)

    def download(self, name: str, dest: Path) -> Path:
        self._transfer("download", self.tag, "--pattern", name, "--dir", str(dest))
        return dest / name

    def upload(self, path: Path) -> None:
        if not self._exists:
            try:
                self._gh("release", "view", self.tag)
            except subprocess.CalledProcessError:
                self._gh(
                    # prerelease: GitHub's "Latest" badge then stays on the open data
                    "release", "create", self.tag, "--prerelease", "--latest=false",
                    "--title", "Lake state (pipeline input, not the open data)",
                    "--notes", RELEASE_NOTES,
                )  # fmt: skip
            self._exists = True
        # --clobber deletes the old asset before uploading; if every try fails, pushing
        # again fixes it, since the local lake still holds everything.
        self._transfer("upload", self.tag, str(path))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack(root: Path, paths: list[str], out: Path) -> Path:
    """Tar lake-relative paths with fixed metadata, so equal content gives equal bytes."""
    with tarfile.open(out, "w", format=tarfile.GNU_FORMAT) as tar:
        for path in sorted(paths):
            info = tar.gettarinfo(root / path, arcname=path)
            info.mtime, info.mode, info.uid, info.gid, info.uname, info.gname = (
                0,
                0o644,
                0,
                0,
                "",
                "",
            )
            with (root / path).open("rb") as f:
                tar.addfile(info, f)
    return out


def unpack(
    tar_path: Path, root: Path, prefixes: tuple[str, ...], only: set[str] | None = None
) -> None:
    """Extract a lake tar, refusing members outside the expected lake paths."""
    with tarfile.open(tar_path) as tar:
        members = tar.getmembers()
        for m in members:
            if not m.isfile() or ".." in m.name.split("/") or not m.name.startswith(prefixes):
                raise ValueError(f"Unexpected member {m.name!r} in {tar_path.name}")
        if only is not None:
            members = [m for m in members if m.name in only]
        tar.extractall(root, members=members, filter="data")


def _bronze_files(root: Path) -> list[str]:
    tables = root / "bronze/tables"
    files = [p.relative_to(root).as_posix() for p in tables.rglob("*") if p.is_file()]
    return files + [MANIFEST_PATH]


def pdf_years(root: Path) -> dict[str, dict[str, str]]:
    """Listing year (YYYY) -> {lake path: sha256} for every PDF the manifest holds."""
    rows = pq.read_table(root / MANIFEST_PATH, columns=["lake_path", "sha256"]).to_pylist()
    years: dict[str, dict[str, str]] = defaultdict(dict)
    for row in rows:
        if row["lake_path"] and row["sha256"]:
            m = _YEAR.search(row["lake_path"])
            if m is None:
                raise ValueError(f"Manifest path has no year= folder: {row['lake_path']!r}")
            years[m[1]][row["lake_path"]] = row["sha256"]
    return dict(years)


def _fetch(release: Release, remote: dict[str, str], name: str, dest: Path) -> Path:
    """Download an asset and check it against the sha256 the release reports."""
    path = release.download(name, dest)
    if remote[name] and sha256_of(path) != remote[name]:
        raise ValueError(f"Downloaded {name} does not match its release sha256")
    return path


def push(root: Path, release: Release) -> int:
    """Upload every asset whose content changed; return how many were uploaded."""
    remote = release.assets()
    uploaded = 0
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        def send(name: str, paths: list[str]) -> None:
            nonlocal uploaded
            tar = pack(root, paths, tmp_dir / name)
            if remote.get(name) == sha256_of(tar):
                logger.debug("%s unchanged", name)
            else:
                logger.info(
                    "Uploading %s (%d files, %.1f MB)", name, len(paths), tar.stat().st_size / 1e6
                )
                release.upload(tar)
                uploaded += 1
            tar.unlink()

        for year, files in sorted(pdf_years(root).items()):
            name = f"pdfs-{year}.tar"
            missing = {p for p in files if not (root / p).is_file()}
            if len(missing) == len(files):
                continue  # nothing of this year here, so nothing changed
            if missing:
                if name not in remote:
                    raise FileNotFoundError(
                        f"{len(missing)} PDFs of {year} are neither here nor in the release"
                    )
                unpack(_fetch(release, remote, name, tmp_dir), root, PDF_PREFIXES, only=missing)
            for path, sha in files.items():
                if sha256_of(root / path) != sha:
                    raise ValueError(
                        f"{path} does not match its manifest sha256; not pushing {year}"
                    )
            send(name, list(files))
        send(BRONZE_ASSET, _bronze_files(root))  # last: it lists the PDFs above
    logger.info("Lake pushed: %d assets uploaded", uploaded)
    return uploaded


def pull(root: Path, release: Release, *, pdfs: bool = False) -> None:
    """Restore bronze tables and manifest (and, with ``pdfs``, every PDF) into the lake."""
    remote = release.assets()
    if BRONZE_ASSET not in remote:
        raise FileNotFoundError(f"The release has no {BRONZE_ASSET}; push a lake first")
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        unpack(_fetch(release, remote, BRONZE_ASSET, Path(tmp)), root, BRONZE_PREFIXES)
        for name in sorted(remote) if pdfs else []:
            if name.startswith("pdfs-"):
                unpack(_fetch(release, remote, name, Path(tmp)), root, PDF_PREFIXES)
                (Path(tmp) / name).unlink()
    logger.info("Lake pulled into %s%s", root, " with PDFs" if pdfs else "")
