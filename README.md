# PodFetch - YouTube Podcast to Google Drive Automation

A production-ready, unattended Python automation system that monitors YouTube podcast channels, discovers new episodes, applies strict filtering (duration, age, shorts/livestreams removal), and uploads full-length episodes to a designated Google Drive folder.

Built for headless Linux cloud machines, Cron jobs, systemd timers, Docker containers, and CI/CD schedulers.

---

## Features

- **Headless & Unattended**: No GUI, no browser popups, zero manual intervention required.
- **Fair Multi-Channel Selection**: Randomly selects between `MIN_VIDEOS_PER_RUN` and `MAX_VIDEOS_PER_RUN` (e.g. 1 to 3) while balancing selections across channels so no single channel dominates.
- **Intelligent Filtering**:
  - Automatically excludes YouTube Shorts.
  - Excludes livestreams / ongoing premieres.
  - Enforces minimum duration (e.g., `>= 20 minutes`).
  - Enforces maximum upload age (e.g., `<= 30 days`).
- **Robust Deduplication**:
  - Persistent SQLite database (`downloads.db`) with unique constraint on `youtube_video_id`.
  - In-flight duplicate detection and pre-upload Drive file search.
- **Crash Recovery & Safe Resume**:
  - Reconciles interrupted jobs automatically on startup.
  - Automatically resets stuck downloads if files were lost during unexpected machine shutdown.
- **High Compatibility & Quality**:
  - Merges video and audio into MP4 container (H.264/AAC preferred) playable directly in Google Drive web players and mobile devices.
- **Isolated Fault Tolerance**:
  - If one video fails to download or upload, subsequent videos continue processing normally.
  - Detailed errors are recorded per-video in SQLite.
- **Dual Authentication**:
  - Service Account (recommended for servers).
  - OAuth 2.0 with Refresh Token (for personal Google Drive).
- **Date Subfolders**:
  - Organizes uploads into `YYYY-MM-DD` subfolders (e.g., `Podcast Videos/2026-10-08/`).

---

## 1. Requirements

- **Operating System**: Linux (Ubuntu 20.04/22.04/24.04, Debian, Rocky, RHEL, CentOS), macOS, or Windows.
- **Python**: Python `3.9` or newer (tested on Python `3.12`).
- **FFmpeg**: Required by `yt-dlp` to merge video and audio streams into an MP4 container.
  - Ubuntu/Debian: `sudo apt update && sudo apt install -y ffmpeg`
  - RHEL/Rocky: `sudo dnf install -y ffmpeg`
  - macOS: `brew install ffmpeg`

---

## 2. Project Structure

```
PodFetch/
├── main.py              # CLI entry point and pipeline orchestrator
├── config.py            # Strongly-typed configuration loader & validator
├── database.py          # SQLite persistence, deduplication, and crash recovery
├── discovery.py         # Channel inspection, canonical resolution, and fair selection
├── filters.py           # Podcast candidate filtering rules
├── downloader.py        # yt-dlp wrapper with retries, exponential backoff & verification
├── drive_uploader.py    # Google Drive v3 chunked resumable uploader
├── filename_utils.py    # Sanitization and standardized naming utilities
├── logger.py            # Console and rotating file logger (logs/automation.log)
├── setup_oauth.py       # OAuth helper script to generate token.json
├── requirements.txt     # Python package dependencies
├── .env                 # Production configuration & credentials
├── .env.example         # Template configuration file
├── credentials.json     # Google Cloud OAuth client credentials
├── token.json           # Authorized Google OAuth token
├── pytest.ini           # Pytest runner configuration
├── README.md            # Complete documentation
├── downloads.db         # Persistent SQLite database (auto-created)
├── logs/                # Execution logs (auto-created)
├── temp/                # Workspace for temporary chunks (auto-created & cleaned)
└── tests/               # Automated test suite
```

---

## 3. Installation

1. **Clone or transfer the repository to your machine**:
   ```bash
   git clone https://github.com/zeishansheikh/PodFetch.git
   cd PodFetch
   ```

2. **Create a Python virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Verify FFmpeg installation**:
   ```bash
   ffmpeg -version
   ```

---

## 4. Google Drive API Setup

### Step 1: Enable Google Drive API in Google Cloud Console
1. Go to the [Google Cloud Console](https://console.cloud.google.com/).
2. Create a new project (e.g. `Podcast-Automation`).
3. In the search bar, search for **Google Drive API** and click **Enable**.

### Step 2: Create Credentials (Choose Option A or Option B)

#### OPTION A: Service Account (Recommended for Unattended Servers)
1. Go to **APIs & Services > Credentials**.
2. Click **Create Credentials > Service Account**.
3. Name it `drive-automation-runner` and click **Create and Continue**.
4. Skip role assignments (Drive folders handle access directly) and click **Done**.
5. Click on your newly created service account in the list, navigate to the **Keys** tab.
6. Click **Add Key > Create new key > JSON**.
7. Download the JSON key file and place it on your server (e.g. `service_account.json`).
8. **CRITICAL STEP**: Open Google Drive in your browser, locate your target folder, click **Share**, and share the folder with the Service Account email address (e.g. `drive-automation-runner@your-project.iam.gserviceaccount.com`) with **Editor** permissions.
9. Copy the **Folder ID** from the browser URL:
   `https://drive.google.com/drive/folders/1aBcDeFgHiJkLmNoPqRsTuVwXyZ`
   Folder ID = `1aBcDeFgHiJkLmNoPqRsTuVwXyZ`

#### OPTION B: OAuth 2.0 (For Personal Google Drive)
If you prefer uploads to appear in your personal Drive without sharing to a service account:
1. Go to **APIs & Services > Credentials**.
2. Create an **OAuth 2.0 Client ID** (Desktop Application).
3. Set `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and obtain a one-time `GOOGLE_REFRESH_TOKEN`.

---

## 5. Configuration (`.env`)

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Edit `.env` with your settings:

```env
# List of YouTube channels to monitor (URLs, IDs, or @handles)
YOUTUBE_CHANNELS=[
    "https://www.youtube.com/@hubermanlab",
    "https://www.youtube.com/@lexfridman",
    "https://www.youtube.com/@TED"
]

# Random selection range per run
MIN_VIDEOS_PER_RUN=1
MAX_VIDEOS_PER_RUN=3

# Target Google Drive folder ID
GOOGLE_DRIVE_FOLDER_ID="1aBcDeFgHiJkLmNoPqRsTuVwXyZ"

# Video filtering criteria
MAX_VIDEO_AGE_DAYS=30
MIN_DURATION_MINUTES=20
ALLOW_SHORTS=false
ALLOW_LIVESTREAMS=false

# Organize into YYYY-MM-DD subfolders in Drive
USE_DATE_SUBFOLDERS=true

# Set to true to test channel inspection without downloading/uploading
DRY_RUN=false

# Service Account path (or GOOGLE_SERVICE_ACCOUNT_JSON)
GOOGLE_SERVICE_ACCOUNT_FILE="service_account.json"
```

---

## 6. How to Add YouTube Channels

The system supports multiple channel formats. You can specify any of the following in `YOUTUBE_CHANNELS`:

- **Handle URL**: `"https://www.youtube.com/@hubermanlab"`
- **Channel ID URL**: `"https://www.youtube.com/channel/UC2D2CMWXMOVWxXXBrRzkQFQ"`
- **Custom URL**: `"https://www.youtube.com/c/lexfridman"`
- **Handle shorthand**: `"@lexfridman"`
- **Channel ID shorthand**: `"UC2D2CMWXMOVWxXXBrRzkQFQ"`

The system automatically targets the `/videos` tab to avoid Shorts and community posts.

---

## 7. How Duplicate Detection Works

1. **Persistent Unique Key**: Every discovered YouTube video is identified by its unique 11-character video ID (`youtube_video_id`).
2. **SQLite Database Checks**: Before downloading, the database is queried. If the video has already been marked as `UPLOADED` or `SKIPPED`, it is immediately bypassed.
3. **Google Drive Verification**: Before initiating upload, the target Drive folder is searched for an identical filename. If the file is already in Google Drive, the existing Drive file ID is recorded and re-upload is skipped.
4. **Resumable State Reconciliation**: If the cloud server loses power mid-process:
   - Any video marked as `DOWNLOADING` with missing temporary files is safely reset to `DISCOVERED` so it will be retried on the next run.
   - Any completed file marked as `DOWNLOADED` will be uploaded directly.

---

## 8. CLI Usage

### Basic Run (Standard Production Mode)
```bash
python main.py
```

### Dry Run (Test discovery & filtering without downloading or uploading)
```bash
python main.py --dry-run
```

### Limit Number of Videos
Download exactly 1 video on this run:
```bash
python main.py --limit 1
```

### Single Channel Mode
Run automation only for a specific channel:
```bash
python main.py --channel "https://www.youtube.com/@hubermanlab"
```

### View Database Status
View total records, status breakdown, completed uploads per channel, and recent failure logs:
```bash
python main.py --status
```

### Retry Failed Videos
Reset all previously failed video records back to `DISCOVERED` so they can be re-attempted:
```bash
python main.py --retry-failed
```

---

## 9. Scheduled Execution on Linux (Cron & Systemd)

Because the script is fully headless and non-interactive, it is 100% compatible with external schedulers.

### Method 1: Using Cron (Daily at 03:00 AM)
1. Open the crontab editor:
   ```bash
   crontab -e
   ```
2. Add the following entry:
   ```cron
   0 3 * * * cd /opt/PodFetch && /opt/PodFetch/.venv/bin/python main.py >> /opt/PodFetch/logs/cron.log 2>&1
   ```

### Method 2: Using Systemd Timer (Recommended for Enterprise Servers)
1. Create `/etc/systemd/system/podfetch.service`:
   ```ini
   [Unit]
   Description=PodFetch - YouTube Podcast to Google Drive Automation
   After=network-online.target

   [Service]
   Type=oneshot
   User=zeeshan
   WorkingDirectory=/opt/PodFetch
   ExecStart=/opt/PodFetch/.venv/bin/python main.py
   StandardOutput=append:/opt/PodFetch/logs/systemd.log
   StandardError=append:/opt/PodFetch/logs/systemd.log

   [Install]
   WantedBy=multi-user.target
   ```

2. Create `/etc/systemd/system/podfetch.timer`:
   ```ini
   [Unit]
   Description=Run PodFetch Daily at 3 AM

   [Timer]
   OnCalendar=*-*-* 03:00:00
   Persistent=true

   [Install]
   Timers.target
   ```

3. Enable and start the timer:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now podfetch.timer
   ```

---

## 10. Running the Test Suite

Run the full automated test suite (database schema, filtering, fair selection, sanitization, and error isolation):

```bash
pytest -v
```

All 24 test cases will execute and validate the pipeline.

---

## 11. Troubleshooting Common Errors

### 1. `GoogleDriveAuthError: No valid Google Drive credentials found`
- Verify that `GOOGLE_SERVICE_ACCOUNT_FILE` points to a valid JSON file, or set `GOOGLE_SERVICE_ACCOUNT_JSON` with the raw JSON string.
- If using OAuth, verify `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, and `GOOGLE_REFRESH_TOKEN` are populated in `.env`.

### 2. `HttpError 404: File not found` or `403: Forbidden` when uploading to Drive
- The Service Account does not have permission on the target folder.
- **Fix**: Open Google Drive in your web browser, right-click the target folder, click **Share**, and grant `Editor` permissions to the Service Account email.

### 3. `yt-dlp: Signature extraction failed` or `403 Forbidden` from YouTube
- YouTube periodically updates its web player. Keep `yt-dlp` updated:
  ```bash
  pip install --upgrade yt-dlp
  ```

### 4. Machine restarted while downloading
- The script automatically checks `downloads.db` on startup and recovers interrupted states, resetting broken downloads cleanly. No manual database cleanup is needed.
