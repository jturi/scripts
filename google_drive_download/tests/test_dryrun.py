"""Offline test of the --dry-run path with a mocked Drive service.

Exercises enumeration parsing, biggest-first ordering, folder-path rebuilding,
duplicate-name dedupe, orphaned-parent fallback, and native-file export naming
without any network access or OAuth credentials.
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import download_drive_data as d

FAKE_ITEMS = [
    {"id": "root1", "name": "Photos", "mimeType": d.FOLDER_MIME, "parents": []},
    {"id": "sub1", "name": "2024", "mimeType": d.FOLDER_MIME, "parents": ["root1"]},
    {"id": "f1", "name": "movie.mkv", "mimeType": "video/x-matroska",
     "size": "5368709120", "md5Checksum": "abc", "parents": ["sub1"]},
    {"id": "f2", "name": "archive.zip", "mimeType": "application/zip",
     "size": "1073741824", "md5Checksum": "def", "parents": ["root1"]},
    {"id": "f3", "name": "notes.txt", "mimeType": "text/plain",
     "size": "1024", "md5Checksum": "ghi", "parents": []},
    {"id": "f4", "name": "Quarterly Report",
     "mimeType": "application/vnd.google-apps.document", "parents": ["root1"]},
    {"id": "f5", "name": "movie.mkv", "mimeType": "video/x-matroska",
     "size": "2048", "md5Checksum": "zzz", "parents": ["sub1"]},
    {"id": "f6", "name": "orphan.bin", "mimeType": "application/octet-stream",
     "size": "500", "md5Checksum": "o", "parents": ["missing_parent"]},
    {"id": "f7", "name": "survey",
     "mimeType": "application/vnd.google-apps.form", "parents": ["root1"]},
]


def run_dry_run():
    fake_resp = mock.MagicMock()
    fake_resp.execute.return_value = {"files": FAKE_ITEMS}
    fake_service = mock.MagicMock()
    fake_service.files.return_value.list.return_value = fake_resp
    with mock.patch.object(d, "get_credentials", return_value=mock.MagicMock()), \
         mock.patch.object(d.ServiceFactory, "service", return_value=fake_service):
        return d.main(["--dry-run", "-o", "/tmp/drive_test_out"])


def test_plan_logic():
    folders = d.build_path_index(FAKE_ITEMS)
    plan = d.build_download_plan(FAKE_ITEMS, export_google_docs=True,
                                 output_dir=d.Path("/tmp/drive_test_out"))
    paths = [str(f.rel_path) for f in plan]

    # Biggest-first ordering (native size-0 sorts last).
    sizes = [f.size for f in plan]
    assert sizes == sorted(sizes, reverse=True), sizes

    # Folder hierarchy rebuilt from nested parents.
    assert os.path.join("Photos", "2024", "movie.mkv") in paths, paths

    # Duplicate name in the same folder is de-duped.
    assert any(p.endswith("movie (1).mkv") for p in paths), paths

    # Missing parent falls back to _orphaned/.
    assert any(p.startswith("_orphaned") for p in paths), paths

    # Native Google Doc is exported with a .docx extension.
    assert any(p.endswith("Quarterly Report.docx") for p in paths), paths

    # Unsupported native type (Form) is skipped.
    assert not any("survey" in p for p in paths), paths

    # 9 items -> 2 folders, 1 unsupported native => 6 downloadable files.
    assert len(plan) == 6, len(plan)
    print("OK: plan has 6 files in correct order:")
    for f in plan:
        size = d._human(f.size) if f.size else "native"
        print(f"  {size:>10}  {f.rel_path}")


if __name__ == "__main__":
    test_plan_logic()
    rc = run_dry_run()
    assert rc == 0, f"dry-run exit code {rc}"
    print("\nAll dry-run assertions passed.")
