#!/usr/bin/env python3
"""Mirror a Google Drive to a local directory.

Downloads every non-trashed file from your Google Drive, biggest files first,
in parallel across threads, idempotently (re-runs only fetch missing/changed
files), with a live byte-based progress bar showing dynamic speed and ETA.

Dependencies:
    pip install google-api-python-client google-auth google-auth-oauthlib \
                google-auth-httplib2 tqdm

(`tqdm` is optional; the script falls back to a plain progress line without it.)

Usage:
    python download_drive_data.py -o ./drive_download --workers 8

First run opens a browser for OAuth consent (needs `credentials.json`, an
OAuth *Desktop app* client secret from Google Cloud Console). The resulting
token is saved to `token.json` and refreshed automatically afterwards.
"""

from __future__ import annotations

import argparse
import io
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
from typing import Iterable, Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

try:
    from tqdm import tqdm  # type: ignore
except ImportError:  # pragma: no cover - optional dependency
    tqdm = None  # type: ignore

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

LIST_FIELDS = (
    "nextPageToken, files(id, name, size, mimeType, md5Checksum, "
    "modifiedTime, parents, exportLinks)"
)

# Google-native MIME -> (export MIME, file extension)
EXPORT_MAP: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}

log = logging.getLogger("drive_download")

# Errors that warrant a retry with backoff.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRYABLE_EXC = (socket.timeout, ssl.SSLError, ConnectionError, TimeoutError, OSError)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class DriveFile:
    id: str
    name: str
    mime_type: str
    size: int  # 0 for native files (unknown until exported)
    md5: Optional[str]
    modified_time: Optional[str]
    parents: list[str]
    is_native: bool
    export_mime: Optional[str] = None
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
            "Create an OAuth 'Desktop app' client in Google Cloud Console, "
            "download it as credentials.json, and place it here."
        )

    log.info("Starting OAuth consent flow")
    flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
    creds = flow.run_local_server(port=0)
    token_path.write_text(creds.to_json())
    log.info("Saved token to %s", token_path)
    return creds


# --------------------------------------------------------------------------- #
# Per-thread Drive service (the client is not thread-safe to share)
# --------------------------------------------------------------------------- #
class ServiceFactory:
    """Builds one Drive API service per thread via thread-local storage."""

    def __init__(self, creds: Credentials):
        self._creds = creds
        self._local = threading.local()

    def service(self):
        svc = getattr(self._local, "service", None)
        if svc is None:
            # cache_discovery=False avoids noisy warnings and file cache use.
            svc = build("drive", "v3", credentials=self._creds, cache_discovery=False)
            self._local.service = svc
        return svc


# --------------------------------------------------------------------------- #
# Retry helper
# --------------------------------------------------------------------------- #
def with_retry(fn, *, max_retries: int, what: str):
    """Call fn() with exponential backoff + jitter on transient failures."""
    attempt = 0
    while True:
        try:
            return fn()
        except HttpError as exc:
            status = getattr(exc.resp, "status", None)
            status = int(status) if status is not None else None
            # 403 is retryable only when it is a rate-limit/userRateLimit reason.
            retryable = status in RETRYABLE_STATUS or (
                status == 403 and _is_rate_limit(exc)
            )
            if not retryable or attempt >= max_retries:
                raise
        except RETRYABLE_EXC:
            if attempt >= max_retries:
                raise
        attempt += 1
        delay = min(60.0, (2 ** attempt)) + random.uniform(0, 1)
        log.debug("Retry %d/%d for %s in %.1fs", attempt, max_retries, what, delay)
        time.sleep(delay)


def _is_rate_limit(exc: HttpError) -> bool:
    text = str(exc).lower()
    return "ratelimit" in text or "rate limit" in text or "user rate" in text


# --------------------------------------------------------------------------- #
# Enumeration
# --------------------------------------------------------------------------- #
def list_all_items(service, include_shared_drives: bool, max_retries: int) -> list[dict]:
    items: list[dict] = []
    page_token: Optional[str] = None
    params = dict(
        q="trashed = false",
        fields=LIST_FIELDS,
        pageSize=1000,
        supportsAllDrives=True,
        includeItemsFromAllDrives=include_shared_drives,
        corpora="allDrives" if include_shared_drives else "user",
    )
    if include_shared_drives:
        params["includeItemsFromAllDrives"] = True
    while True:
        page_params = dict(params)
        if page_token:
            page_params["pageToken"] = page_token
        resp = with_retry(
            lambda: service.files().list(**page_params).execute(),
            max_retries=max_retries,
            what="files.list",
        )
        items.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        log.debug("Listed %d items so far", len(items))
        if not page_token:
            break
    return items


_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize(name: str) -> str:
    name = _INVALID_CHARS.sub("_", name).strip().rstrip(". ")
    return name or "_unnamed"


def build_path_index(items: list[dict]) -> dict[str, dict]:
    """id -> {name, parents} for every folder."""
    return {
        it["id"]: {"name": sanitize(it.get("name", it["id"])), "parents": it.get("parents", [])}
        for it in items
        if it.get("mimeType") == FOLDER_MIME
    }


def resolve_rel_dir(parents: list[str], folders: dict[str, dict]) -> Path:
    """Resolve a file's parent folder chain into a relative directory path."""
    if not parents:
        return Path(".")
    parent_id = parents[0]  # deterministic: first parent wins for multi-parented files
    parts: list[str] = []
    seen: set[str] = set()
    while parent_id and parent_id in folders and parent_id not in seen:
        seen.add(parent_id)
        node = folders[parent_id]
        parts.append(node["name"])
        node_parents = node["parents"]
        parent_id = node_parents[0] if node_parents else None
    if parent_id and parent_id not in folders:
        # Parent exists in Drive metadata we cannot see (e.g. shared root) -> orphaned.
        return Path("_orphaned").joinpath(*reversed(parts)) if parts else Path("_orphaned")
    return Path(*reversed(parts)) if parts else Path(".")


def build_download_plan(
    items: list[dict], export_google_docs: bool, output_dir: Path
) -> list[DriveFile]:
    folders = build_path_index(items)
    files: list[DriveFile] = []
    used_paths: set[Path] = set()

    raw_files = [
        it
        for it in items
        if it.get("mimeType") not in (FOLDER_MIME, SHORTCUT_MIME)
    ]

    for it in raw_files:
        mime = it.get("mimeType", "")
        is_native = mime.startswith("application/vnd.google-apps")
        export_mime: Optional[str] = None
        name = sanitize(it.get("name", it["id"]))

        if is_native:
            if not export_google_docs:
                continue
            mapping = EXPORT_MAP.get(mime)
            if mapping is None:
                log.warning("Skipping unsupported native type %s: %s", mime, name)
                continue
            export_mime, ext = mapping
            if not name.lower().endswith(ext):
                name += ext
            size = 0
        else:
            size = int(it.get("size", 0) or 0)

        rel_dir = resolve_rel_dir(it.get("parents", []), folders)
        rel_path = _dedupe(rel_dir / name, used_paths)
        used_paths.add(rel_path)

        files.append(
            DriveFile(
                id=it["id"],
                name=name,
                mime_type=mime,
                size=size,
                md5=it.get("md5Checksum"),
                modified_time=it.get("modifiedTime"),
                parents=it.get("parents", []),
                is_native=is_native,
                export_mime=export_mime,
                rel_path=rel_path,
            )
        )

    # Largest first; native (size 0) sort to the end.
    files.sort(key=lambda f: f.size, reverse=True)
    return files


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
# Idempotency
# --------------------------------------------------------------------------- #
def md5_of(path: Path, chunk: int = 1024 * 1024) -> str:
    import hashlib

    h = hashlib.md5()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def is_up_to_date(df: DriveFile, dest: Path) -> bool:
    if not dest.exists():
        return False
    try:
        local_size = dest.stat().st_size
    except OSError:
        return False
    if df.md5:  # binary file with a known checksum
        if local_size != df.size:
            return False
        return md5_of(dest) == df.md5
    # Exported native files: no checksum -> match on size only (size known post-run).
    # A zero-byte placeholder is never considered complete.
    return local_size > 0


# --------------------------------------------------------------------------- #
# Progress tracking (shared, lock-protected; rendered by one thread)
# --------------------------------------------------------------------------- #
class Progress:
    def __init__(self, total_bytes: int, total_files: int, approximate: bool, enabled: bool):
        self.total_bytes = total_bytes
        self.total_files = total_files
        self.approximate = approximate
        self.enabled = enabled
        self._lock = threading.Lock()
        self._downloaded = 0
        self._files_done = 0
        # rolling window of (timestamp, cumulative_bytes) for dynamic speed
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

    # ---- speed / eta ----
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
        remaining = max(0, self.total_bytes - downloaded)
        eta = remaining / speed if speed > 0 else float("inf")
        return downloaded, files_done, speed, eta

    # ---- rendering ----
    def start(self) -> None:
        if not self.enabled:
            return
        if tqdm is not None:
            self._bar = tqdm(
                total=self.total_bytes,
                unit="B",
                unit_scale=True,
                unit_divisor=1024,
                desc="Downloading" + (" (~)" if self.approximate else ""),
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
                    speed, eta, self.approximate,
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
    speed: float, eta: float, approximate: bool,
) -> None:
    pct = (downloaded / total * 100) if total else 0.0
    width = 30
    filled = int(width * downloaded / total) if total else 0
    bar = "#" * filled + "-" * (width - filled)
    tag = "~" if approximate else ""
    line = (
        f"\r[{bar}] {pct:5.1f}{tag}% "
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
    df: DriveFile,
    factory: ServiceFactory,
    output_dir: Path,
    chunk_size: int,
    max_retries: int,
    progress: Progress,
    stats: Stats,
    stop_event: threading.Event,
) -> None:
    dest = output_dir / df.rel_path
    if stop_event.is_set():
        return
    if is_up_to_date(df, dest):
        log.debug("SKIPPED (up to date): %s", df.rel_path)
        stats.record("skipped")
        # Count its bytes toward the bar so a fully-cached re-run still completes the bar.
        progress.add_bytes(df.size)
        progress.file_done()
        return

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    log.info("STARTED: %s (%s)", df.rel_path, _human(df.size) if df.size else "native")

    try:
        def run_download() -> int:
            svc = factory.service()
            if df.is_native:
                request = svc.files().export_media(fileId=df.id, mimeType=df.export_mime)
            else:
                request = svc.files().get_media(fileId=df.id, supportsAllDrives=True)
            written = 0
            with tmp.open("wb") as fh:
                downloader = MediaIoBaseDownload(fh, request, chunksize=chunk_size)
                done = False
                prev = 0
                while not done:
                    if stop_event.is_set():
                        raise KeyboardInterrupt
                    _status, done = downloader.next_chunk()
                    pos = fh.tell()
                    progress.add_bytes(pos - prev)
                    prev = pos
                written = fh.tell()
                fh.flush()
                os.fsync(fh.fileno())
            return written

        # Retry wraps a fresh attempt; reset the .part each retry.
        def attempt() -> int:
            if tmp.exists():
                tmp.unlink()
            return run_download()

        written = with_retry(attempt, max_retries=max_retries, what=df.name)
        os.replace(tmp, dest)
        log.info("DONE: %s (%s)", df.rel_path, _human(written))
        stats.record("downloaded", nbytes=written)
        progress.file_done()
    except KeyboardInterrupt:
        _cleanup(tmp)
        raise
    except Exception as exc:  # noqa: BLE001 - per-file isolation is required
        _cleanup(tmp)
        log.error("FAILED: %s: %s", df.rel_path, exc)
        stats.record("failed", name=str(df.rel_path), error=str(exc))
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
    p = argparse.ArgumentParser(description="Mirror Google Drive to a local directory.")
    p.add_argument("-o", "--output-dir", type=Path, default=Path("./drive_download"))
    p.add_argument("--token", type=Path, default=Path("token.json"))
    p.add_argument("--credentials", type=Path, default=Path("credentials.json"))
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--include-shared-drives", action="store_true")
    p.add_argument(
        "--export-google-docs",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Export Google Docs/Sheets/Slides to Office formats (default: on).",
    )
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
    factory = ServiceFactory(creds)

    log.info("Enumerating Drive contents...")
    items = list_all_items(factory.service(), args.include_shared_drives, args.max_retries)
    log.info("Found %d items total", len(items))

    plan = build_download_plan(items, args.export_google_docs, args.output_dir)
    total_bytes = sum(f.size for f in plan)
    has_native = any(f.is_native for f in plan)
    log.info("Planned %d files, %s to download", len(plan), _human(total_bytes))

    if args.dry_run:
        for f in plan:
            size = _human(f.size) if f.size else "native"
            print(f"{size:>12}  {f.rel_path}")
        print(f"\nTotal: {len(plan)} files, {_human(total_bytes)}")
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)

    progress_enabled = (not args.no_progress) and sys.stderr.isatty()
    progress = Progress(total_bytes, len(plan), has_native, progress_enabled)
    stats = Stats()
    stop_event = threading.Event()
    chunk_bytes = max(1, args.chunk_size) * 1024 * 1024

    progress.start()
    interrupted = False
    try:
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = [
                pool.submit(
                    download_one, df, factory, args.output_dir, chunk_bytes,
                    args.max_retries, progress, stats, stop_event,
                )
                for df in plan
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
