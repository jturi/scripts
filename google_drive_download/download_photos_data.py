#!/usr/bin/env python3
"""Mirror your Google Photos library to a local directory.

Downloads every media item (photos and videos) from your Google Photos
library, in parallel across threads, idempotently (re-runs only fetch missing
files), with a live progress line showing transferred bytes, speed and ETA.

Because the Photos Library API exposes no folder structure, media is laid out
by capture date as ``YYYY/MM/<filename>`` (undated items go to ``_undated``).

Dependencies:
    pip install google-api-python-client google-auth google-auth-oauthlib \
                google-auth-httplib2 requests tqdm

(`tqdm` is optional; the script falls back to a plain progress line without it.)

Usage:
    python download_photos_data.py -o ./photos_download --workers 8

First run opens an OAuth consent flow (needs `credentials.json`, an OAuth
*Desktop app* client secret from Google Cloud Console, with the Photos Library
API enabled). The resulting token is saved to `token.json` and refreshed
automatically afterwards.

Notes / caveats:
  * The Photos Library API does NOT return file sizes or checksums, so the
    total size is unknown up front (the progress bar is byte-based but has no
    percentage/ETA) and idempotency is "exists and non-empty" rather than a
    checksum comparison.
  * Media ``baseUrl``s expire ~60 minutes after they are listed. For very
    large libraries a download may outlive its URL and fail with 403; just
    re-run — already-downloaded files are skipped and fresh URLs are fetched.
  * Originals are requested with the ``=d`` (photos) / ``=dv`` (videos)
    parameters. Google may still re-encode some formats server-side.
"""

from __future__ import annotations

import argparse
import logging
import os
import random
import re
import socket
import ssl
import sys
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import AuthorizedSession, Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

try:
    from tqdm import tqdm  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    tqdm = None  # type: ignore

SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]
API_BASE = "https://photoslibrary.googleapis.com/v1"
PAGE_SIZE = 100  # mediaItems.list maximum

log = logging.getLogger("photos_download")

# Errors that warrant a retry with backoff.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_EXC = (
    socket.timeout,
    ssl.SSLError,
    ConnectionError,
    TimeoutError,
    OSError,
    requests.ConnectionError,
    requests.Timeout,
)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class PhotoItem:
    id: str
    filename: str
    mime_type: str
    base_url: str
    creation_time: Optional[str]
    is_video: bool
    rel_path: Path = field(default_factory=Path)  # filled in after path resolution


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def get_credentials(token_path: Path, creds_path: Path) -> Credentials:
    creds: Optional[Credentials] = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except (ValueError, KeyError) as exc:
            log.warning("Could not load token %s: %s", token_path, exc)
            creds = None

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            log.info("Refreshing expired access token")
            creds.refresh(Request())
            token_path.write_text(creds.to_json())
            return creds
        except RefreshError as exc:
            log.warning("Token refresh failed (%s); re-running consent flow", exc)
            creds = None

    if not creds_path.exists():
        raise SystemExit(
            f"No valid token and client secrets file not found: {creds_path}\n"
            "Create an OAuth 'Desktop app' client in Google Cloud Console "
            "(with the Photos Library API enabled), download it as "
            "credentials.json, and place it here."
        )

    log.info("Starting OAuth consent flow")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    # Don't try to auto-launch a browser (fails on headless/SSH hosts); print the
    # URL so it can be opened manually. The local server still catches the
    # redirect, so this works as long as the browser can reach this host's
    # localhost (same machine, or via `ssh -L <port>:localhost:<port>`).
    creds = flow.run_local_server(port=0, open_browser=False)
    token_path.write_text(creds.to_json())
    log.info("Saved token to %s", token_path)
    return creds


# --------------------------------------------------------------------------- #
# Per-thread authorized session (requests.Session is reused per thread)
# --------------------------------------------------------------------------- #
class SessionFactory:
    """Builds one AuthorizedSession per thread via thread-local storage."""

    def __init__(self, creds: Credentials):
        self._creds = creds
        self._local = threading.local()

    def session(self) -> AuthorizedSession:
        sess = getattr(self._local, "session", None)
        if sess is None:
            sess = AuthorizedSession(self._creds)
            self._local.session = sess
        return sess


# --------------------------------------------------------------------------- #
# Retry helper
# --------------------------------------------------------------------------- #
def with_retry(fn, *, max_retries: int, what: str):
    """Call fn() with exponential backoff + jitter on transient failures."""
    attempt = 0
    while True:
        try:
            return fn()
        except requests.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status not in RETRYABLE_STATUS or attempt >= max_retries:
                raise
        except RETRYABLE_EXC:
            if attempt >= max_retries:
                raise
        attempt += 1
        delay = min(60.0, (2 ** attempt)) + random.uniform(0, 1)
        log.debug("Retry %d/%d for %s in %.1fs", attempt, max_retries, what, delay)
        time.sleep(delay)


# --------------------------------------------------------------------------- #
# Enumeration
# --------------------------------------------------------------------------- #
def list_all_items(session: AuthorizedSession, max_retries: int) -> list[dict]:
    items: list[dict] = []
    page_token: Optional[str] = None
    url = f"{API_BASE}/mediaItems"
    while True:
        params = {"pageSize": PAGE_SIZE}
        if page_token:
            params["pageToken"] = page_token

        def fetch() -> dict:
            resp = session.get(url, params=params, timeout=60)
            resp.raise_for_status()
            return resp.json()

        data = with_retry(fetch, max_retries=max_retries, what="mediaItems.list")
        items.extend(data.get("mediaItems", []))
        page_token = data.get("nextPageToken")
        log.debug("Listed %d items so far", len(items))
        if not page_token:
            break
    return items


_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str) -> str:
    name = _INVALID_CHARS.sub("_", name).strip().rstrip(". ")
    return name or "_unnamed"


def _date_dir(creation_time: Optional[str]) -> Path:
    """Map an RFC3339 creationTime (e.g. 2023-08-15T12:34:56Z) to YYYY/MM."""
    if creation_time and len(creation_time) >= 7:
        year, month = creation_time[:4], creation_time[5:7]
        if year.isdigit() and month.isdigit():
            return Path(year) / month
    return Path("_undated")


def build_download_plan(items: list[dict]) -> list[PhotoItem]:
    plan: list[PhotoItem] = []
    used_paths: set[Path] = set()

    for it in items:
        meta = it.get("mediaMetadata", {})
        is_video = "video" in meta
        if is_video and meta["video"].get("status") not in (None, "READY"):
            log.warning("Skipping video still processing: %s", it.get("filename", it["id"]))
            continue
        base_url = it.get("baseUrl")
        if not base_url:
            log.warning("Skipping item without baseUrl: %s", it.get("filename", it["id"]))
            continue

        filename = sanitize(it.get("filename", it["id"]))
        rel_dir = _date_dir(meta.get("creationTime"))
        rel_path = _dedupe(rel_dir / filename, used_paths)
        used_paths.add(rel_path)

        plan.append(
            PhotoItem(
                id=it["id"],
                filename=filename,
                mime_type=it.get("mimeType", ""),
                base_url=base_url,
                creation_time=meta.get("creationTime"),
                is_video=is_video,
                rel_path=rel_path,
            )
        )

    # Newest first (creationTime sorts lexicographically for RFC3339 / Z timestamps).
    plan.sort(key=lambda p: p.creation_time or "", reverse=True)
    return plan


def _dedupe(rel_path: Path, used: set[Path]) -> Path:
    if rel_path not in used:
        return rel_path
    stem, suffix = rel_path.stem, rel_path.suffix
    parent = rel_path.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if candidate not in used:
            return candidate
        i += 1


# --------------------------------------------------------------------------- #
# Idempotency (Photos API gives no size/checksum -> "exists and non-empty")
# --------------------------------------------------------------------------- #
def is_up_to_date(dest: Path) -> bool:
    try:
        return dest.exists() and dest.stat().st_size > 0
    except OSError:
        return False


# --------------------------------------------------------------------------- #
# Progress tracking (shared, lock-protected; rendered by one thread)
# --------------------------------------------------------------------------- #
class Progress:
    """Byte-based progress. total_bytes <= 0 means the total is unknown
    (no percentage / ETA), which is the Photos case."""

    def __init__(self, total_bytes: int, total_files: int, enabled: bool):
        self.total_bytes = total_bytes
        self.total_files = total_files
        self.indeterminate = total_bytes <= 0
        self.enabled = enabled
        self._lock = threading.Lock()
        self._downloaded = 0
        self._files_done = 0
        self._samples: deque[tuple[float, int]] = deque()
        self._window = 4.0  # seconds
        self._stop = threading.Event()
        self._bar = None
        self._renderer: Optional[threading.Thread] = None
        self._start = time.monotonic()

    # ---- worker-side updates ----
    def add_bytes(self, n: int) -> None:
        if n <= 0:
            return
        with self._lock:
            self._downloaded += n
            now = time.monotonic()
            self._samples.append((now, self._downloaded))
            self._trim(now)

    def file_done(self) -> None:
        with self._lock:
            self._files_done += 1

    def _trim(self, now: float) -> None:
        while len(self._samples) > 1 and now - self._samples[0][0] > self._window:
            self._samples.popleft()

    def _speed(self, now: float) -> float:
        if len(self._samples) < 2:
            return 0.0
        t0, b0 = self._samples[0]
        t1, b1 = self._samples[-1]
        dt = t1 - t0
        return (b1 - b0) / dt if dt > 0 else 0.0

    def snapshot(self) -> tuple[int, int, float, float]:
        now = time.monotonic()
        with self._lock:
            self._trim(now)
            downloaded = self._downloaded
            files_done = self._files_done
            speed = self._speed(now)
        if self.indeterminate:
            eta = float("inf")
        else:
            remaining = max(0, self.total_bytes - downloaded)
            eta = remaining / speed if speed > 0 else float("inf")
        return downloaded, files_done, speed, eta

    # ---- rendering ----
    def start(self) -> None:
        if not self.enabled:
            return
        if tqdm is not None:
            self._bar = tqdm(
                total=None if self.indeterminate else self.total_bytes,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc="Downloading",
                dynamic_ncols=True,
                file=sys.stderr,
            )
        self._renderer = threading.Thread(target=self._loop, daemon=True)
        self._renderer.start()

    def _loop(self) -> None:
        last = 0
        while not self._stop.is_set():
            downloaded, files_done, speed, eta = self.snapshot()
            if self._bar is not None:
                self._bar.update(downloaded - last)
                last = downloaded
                self._bar.set_postfix_str(
                    f"{files_done}/{self.total_files} files, "
                    f"{_human(speed)}/s, ETA {_fmt_eta(eta)}",
                    refresh=False,
                )
            else:
                _render_plain(
                    downloaded, self.total_bytes, files_done, self.total_files,
                    speed, eta, self.indeterminate,
                )
            self._stop.wait(0.25)

    def stop(self) -> None:
        self._stop.set()
        if self._renderer is not None:
            self._renderer.join(timeout=2)
        if self._bar is not None:
            downloaded, _, _, _ = self.snapshot()
            self._bar.update(max(0, downloaded - self._bar.n))
            self._bar.close()
        elif self.enabled:
            sys.stderr.write("\n")
            sys.stderr.flush()


def _human(num: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


def _fmt_eta(seconds: float) -> str:
    if seconds == float("inf") or seconds != seconds:  # inf or NaN
        return "--:--"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def _render_plain(
    downloaded: int, total: int, files_done: int, total_files: int,
    speed: float, eta: float, indeterminate: bool,
) -> None:
    if indeterminate:
        line = (
            f"\r{_human(downloaded)} transferred "
            f"{_human(speed)}/s "
            f"[{files_done}/{total_files} files]"
        )
    else:
        pct = (downloaded / total * 100) if total else 0.0
        width = 30
        filled = int(width * downloaded / total) if total else 0
        bar = "#" * filled + "-" * (width - filled)
        line = (
            f"\r[{bar}] {pct:5.1f}% "
            f"{_human(downloaded)}/{_human(total)} "
            f"{_human(speed)}/s ETA {_fmt_eta(eta)} "
            f"[{files_done}/{total_files} files]"
        )
    sys.stderr.write(line)
    sys.stderr.flush()


# --------------------------------------------------------------------------- #
# Download
# --------------------------------------------------------------------------- #
@dataclass
class Stats:
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    bytes: int = 0
    failures: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, kind: str, *, nbytes: int = 0, name: str = "", error: str = "") -> None:
        with self._lock:
            if kind == "downloaded":
                self.downloaded += 1
                self.bytes += nbytes
            elif kind == "skipped":
                self.skipped += 1
            elif kind == "failed":
                self.failed += 1
                self.failures.append(f"{name}: {error}")


def download_one(
    item: PhotoItem,
    factory: SessionFactory,
    output_dir: Path,
    chunk_size: int,
    max_retries: int,
    progress: Progress,
    stats: Stats,
    stop_event: threading.Event,
) -> None:
    dest = output_dir / item.rel_path
    if stop_event.is_set():
        return
    if is_up_to_date(dest):
        log.debug("SKIPPED (already present): %s", item.rel_path)
        stats.record("skipped")
        progress.file_done()
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    # "=d" downloads photo originals (with EXIF); "=dv" downloads video bytes.
    url = item.base_url + ("=dv" if item.is_video else "=d")
    log.info("STARTED: %s", item.rel_path)

    try:
        def run_download() -> int:
            session = factory.session()
            written = 0
            with session.get(url, stream=True, timeout=60) as resp:
                resp.raise_for_status()
                with tmp.open("wb") as fh:
                    for chunk in resp.iter_content(chunk_size):
                        if stop_event.is_set():
                            raise KeyboardInterrupt
                        if not chunk:
                            continue
                        fh.write(chunk)
                        written += len(chunk)
                        progress.add_bytes(len(chunk))
                    fh.flush()
                    os.fsync(fh.fileno())
            return written

        def attempt() -> int:
            if tmp.exists():
                tmp.unlink()
            return run_download()

        written = with_retry(attempt, max_retries=max_retries, what=item.filename)
        os.replace(tmp, dest)
        log.info("DONE: %s (%s)", item.rel_path, _human(written))
        stats.record("downloaded", nbytes=written)
        progress.file_done()
    except KeyboardInterrupt:
        _cleanup(tmp)
        raise
    except Exception as exc:  # noqa: BLE001 - per-file isolation is required
        _cleanup(tmp)
        log.error("FAILED: %s: %s", item.rel_path, exc)
        stats.record("failed", name=str(item.rel_path), error=str(exc))
        progress.file_done()


def _cleanup(tmp: Path) -> None:
    try:
        if tmp.exists():
            tmp.unlink()
    except OSError:
        pass


# --------------------------------------------------------------------------- #
# CLI / main
# --------------------------------------------------------------------------- #
def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Mirror Google Photos to a local directory.")
    p.add_argument("-o", "--output-dir", type=Path, default=Path("./photos_download"))
    p.add_argument("--token", type=Path, default=Path("token.json"))
    p.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--chunk-size", type=int, default=16, help="Download chunk size in MB.")
    p.add_argument("--max-retries", type=int, default=5)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-progress", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )

    creds = get_credentials(args.token, args.credentials)
    factory = SessionFactory(creds)

    log.info("Enumerating Google Photos library...")
    items = list_all_items(factory.session(), args.max_retries)
    log.info("Found %d media items total", len(items))

    plan = build_download_plan(items)
    log.info("Planned %d files to download", len(plan))

    if args.dry_run:
        for p in plan:
            kind = "video" if p.is_video else "photo"
            print(f"{kind:>6}  {p.rel_path}")
        print(f"\nTotal: {len(plan)} files")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)

    progress_enabled = (not args.no_progress) and sys.stderr.isatty()
    # Sizes are unknown up front -> indeterminate total (0).
    progress = Progress(0, len(plan), progress_enabled)
    stats = Stats()
    stop_event = threading.Event()
    chunk_bytes = max(1, args.chunk_size) * 1024 * 1024

    progress.start()
    interrupted = False
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [
                pool.submit(
                    download_one, item, factory, args.output_dir, chunk_bytes,
                    args.max_retries, progress, stats, stop_event,
                )
                for item in plan
            ]
            try:
                for fut in as_completed(futures):
                    fut.result()
            except KeyboardInterrupt:
                interrupted = True
                log.warning("Interrupted — cancelling remaining downloads...")
                stop_event.set()
                for fut in futures:
                    fut.cancel()
    except KeyboardInterrupt:
        interrupted = True
        stop_event.set()
    finally:
        progress.stop()

    print("\n--- Summary ---", file=sys.stderr)
    print(f"Files seen:   {len(plan)}", file=sys.stderr)
    print(f"Downloaded:   {stats.downloaded}", file=sys.stderr)
    print(f"Skipped:      {stats.skipped}", file=sys.stderr)
    print(f"Failed:       {stats.failed}", file=sys.stderr)
    print(f"Transferred:  {_human(stats.bytes)}", file=sys.stderr)
    if stats.failures:
        print("Failures:", file=sys.stderr)
        for f in stats.failures:
            print(f"  - {f}", file=sys.stderr)

    if interrupted:
        return 130
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
