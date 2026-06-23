# download_drive_data

Mirror your Google Drive to a local directory. Downloads the largest files
first, runs downloads in parallel across threads, is idempotent (re-runs only
fetch missing/changed files), and shows a live progress bar with dynamic speed
and ETA.

## Install

```bash
pip install google-api-python-client google-auth google-auth-oauthlib \
            google-auth-httplib2 tqdm
```

`tqdm` is optional — without it the script falls back to a plain progress line.

## Getting a Google Drive API token

The script authenticates with OAuth. You need a **`credentials.json`** client
secret once; the script then creates and refreshes **`token.json`** for you.

### 1. Create / select a Google Cloud project
1. Go to <https://console.cloud.google.com/>.
2. Top bar → project picker → **New Project** (or pick an existing one).

### 2. Enable the Drive API
1. Navigation menu → **APIs & Services → Library**.
2. Search for **Google Drive API** → **Enable**.

### 3. Configure the OAuth consent screen
1. **APIs & Services → OAuth consent screen**.
2. User type: **External** (or **Internal** if you have a Workspace org) → **Create**.
3. Fill in app name + your email; you can leave most fields blank.
4. **Scopes**: you can skip adding scopes here (the script requests
   `drive.readonly` at runtime).
5. **Test users**: add the Google account whose Drive you want to download.
   (While the app is in "Testing" status, only listed test users can authorize
   it — this is fine for personal use and the token does not expire as long as
   it is refreshed regularly.)

### 4. Create OAuth client credentials
1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**. Give it any name → **Create**.
3. Click **Download JSON** and save the file as `credentials.json` next to
   `download_drive_data.py`.

> ⚠️ This is an OAuth **client secret**, not a plain "API key". The Drive API
> needs OAuth to access *your* private files; a simple API key only works for
> public data and will not work here.

### 5. First run — authorize and create the token
```bash
python download_drive_data.py -o ./drive_download
```
On the first run a browser window opens asking you to sign in and grant
read-only Drive access. After you approve, the script writes **`token.json`**.
Subsequent runs reuse and silently refresh that token — no browser needed.

If `token.json` is ever deleted or revoked, just re-run and authorize again.
To revoke access entirely: <https://myaccount.google.com/permissions>.

## Usage

```bash
# Basic mirror with 8 parallel workers
python download_drive_data.py -o ./drive_download --workers 8

# Preview what would be downloaded (largest first) without writing anything
python download_drive_data.py --dry-run

# Include Shared Drives, skip exporting Google Docs/Sheets/Slides
python download_drive_data.py --include-shared-drives --no-export-google-docs
```

### Options
| Flag | Default | Description |
|------|---------|-------------|
| `-o`, `--output-dir` | `./drive_download` | Local destination directory. |
| `--token` | `token.json` | OAuth token file (created/refreshed automatically). |
| `--credentials` | `credentials.json` | OAuth client secret from Google Cloud. |
| `--workers` | `4` | Number of concurrent download threads. |
| `--include-shared-drives` | off | Also download files from Shared Drives. |
| `--export-google-docs` / `--no-export-google-docs` | on | Export native Google files to Office formats. |
| `--chunk-size` | `16` | Download chunk size in MB. |
| `--max-retries` | `5` | Retries per file on transient errors. |
| `--dry-run` | off | List the plan; download nothing. |
| `--no-progress` | off | Disable the live progress bar. |
| `-v`, `--verbose` | off | Verbose (DEBUG) logging. |

## Notes
- **Idempotent / resumable**: files are verified by MD5 (or size) and skipped if
  already complete. Interrupted downloads use a `.part` temp file and are never
  mistaken for complete files. Ctrl+C stops cleanly and leaves finished files
  intact.
- **Google Docs/Sheets/Slides** are exported to `.docx` / `.xlsx` / `.pptx`
  (Drawings to `.png`). Google's export endpoint caps exports at ~10 MB.
- The script requests only **read-only** Drive scope and never modifies your
  Drive.
