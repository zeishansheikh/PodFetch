# PodFetch - Multi-Source (YouTube + Pinterest + Instagram) to Google Drive Automation

A production-ready, unattended Python automation system that discovers and downloads content from **YouTube**, **Pinterest**, and **Instagram Trending Audio**, applies strict filtering (duration, aspect ratio, audio licensing, static image removal, shorts/livestreams), and uploads eligible files to a designated Google Drive folder with dedicated platform isolation.

Built for headless Linux cloud machines, Cron jobs, systemd timers, Docker containers, and CI/CD schedulers.

---

## Features

- **Multi-Source Ingestion**:
  - **YouTube**: Discovers podcast videos from configured channels.
  - **Pinterest**: Discovers aesthetic videos matching configured keywords.
  - **Instagram Trending Audio**: Discovers trending audio tracks via official Meta Graph API, collects metadata (title, artist, reel count, trend rank, popularity score), and verifies authorized licensing.
- **Audio Manifest Generation (`audio_manifest.json`)**:
  - Maintains a persistent, atomic JSON manifest that downstream video-processing agents can query to find newly available audio tracks, drive file IDs, and popularity indicators.
- **Graceful API Limitation Reporting**:
  - If official Instagram API credentials or permissions are unavailable, PodFetch reports the exact limitation clearly and cleanly without fabricating fake audio or crashing.
- **Headless & Unattended**: No GUI, no browser popups, zero manual intervention required.
- **Companion Metadata**: Companion `.json` metadata files are uploaded alongside each downloaded audio file to Google Drive.
- **Dedicated Google Drive Isolation**:
  - Separate folders for each platform: `google_drive_folder_id/instagram/`, `google_drive_folder_id/pinterest/`, `google_drive_folder_id/youtube/`, and `google_drive_folder_id/islamic/`.
- **Automated Quran Ayah Reel Builder (`islamic` feature)**:
  - Generates production-ready 1080x1920@60fps reels combining precision-cut Quran recitations with Urdu translations, authentic Tanzil Uthmani calligraphy, and vetted Pinterest backgrounds. See [`quran/README.md`](quran/README.md) for full documentation.
- **Fair & Balanced Selection**: Balances selections across enabled platforms in a round-robin strategy, prioritizing top trending Instagram audio, vertical 9:16 Pinterest videos, and recent YouTube uploads.
- **Robust SQLite Deduplication**:
  - Persistent SQLite database (`downloads.db`) with composite unique constraint on `(platform, source_id)`.
- **Isolated Fault Tolerance**:
  - Failure in one source or file does not interrupt remaining downloads or sources.

---

## 1. Requirements

- **Operating System**: Linux (Ubuntu 20.04/22.04/24.04, Debian, Rocky, RHEL, CentOS), macOS, or Windows.
- **Python**: Python `3.9` or newer (tested on Python `3.12`).
- **FFmpeg & FFprobe**: Required by `yt-dlp` to merge streams and validate media integrity.
  - Ubuntu/Debian: `sudo apt update && sudo apt install -y ffmpeg`
  - RHEL/Rocky: `sudo dnf install -y ffmpeg`
  - macOS: `brew install ffmpeg`

---

## 2. Project Structure

```
PodFetch/
├── main.py                  # CLI entry point and pipeline orchestrator
├── config.py                # Strongly-typed configuration loader & validator
├── database.py              # SQLite persistence, (platform, source_id) deduplication & recovery
├── discovery.py             # Channel inspection & multi-source candidate selection
├── audio_manifest.py        # Audio manifest manager (audio_manifest.json) for video agents
├── instagram_discovery.py   # Meta Graph API trending audio discovery & limitation reporting
├── instagram_downloader.py  # Instagram audio stream downloader & companion metadata writer
├── pinterest_discovery.py   # Pinterest API & resource search, image filtering, keyword tracking
├── pinterest_downloader.py  # Pinterest video downloader with yt-dlp & FFprobe verification
├── downloader.py            # YouTube downloader with retries & exponential backoff
├── filters.py               # Candidate filtering rules (duration, authorization, vertical aspect)
├── drive_uploader.py        # Google Drive v3 chunked uploader with audio/json/video support
├── filename_utils.py        # Sanitization and standardized source naming utilities
├── logger.py                # Console and rotating file logger (logs/automation.log)
├── setup_oauth.py           # OAuth helper script to generate token.json
├── pinterest_keywords.txt   # Configurable Pinterest search keywords (one per line)
├── audio_manifest.json      # Persistent audio manifest for downstream video agents
├── requirements.txt         # Python package dependencies
├── .env                     # Production configuration & credentials
├── .env.example             # Template configuration file
├── downloads.db             # Persistent SQLite database (auto-migrated)
├── logs/                    # Execution logs (auto-created)
├── temp/                    # Temporary download workspace (auto-cleaned)
└── tests/                   # Automated test suite (51 unit & integration tests)
```

---

## 3. Installation

1. **Clone or transfer the repository**:
   ```bash
   git clone https://github.com/zeishansheikh/PodFetch.git
   cd PodFetch
   ```

2. **Create and activate a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -r requirements.txt
   ```

4. **Verify FFmpeg / FFprobe installation**:
   ```bash
   ffprobe -version
   ```

---

## 4. Configuration (`.env` and `pinterest_keywords.txt`)

Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

### Source & Platform Settings

```env
# Enabled sources (comma-separated: youtube, pinterest)
ENABLED_SOURCES=youtube,pinterest
YOUTUBE_ENABLED=true
PINTEREST_ENABLED=true

# Video selection limits per run
MIN_VIDEOS_PER_RUN=1
MAX_VIDEOS_PER_RUN=3

# Target Google Drive folder ID
GOOGLE_DRIVE_FOLDER_ID="1aBcDeFgHiJkLmNoPqRsTuVwXyZ"

# Pinterest Filtering & Preference Settings
PREFER_VERTICAL=true
MIN_VIDEO_DURATION_SECONDS=10
MAX_VIDEO_DURATION_SECONDS=30

# Optional: Path to Pinterest keywords text file (defaults to pinterest_keywords.txt)
PINTEREST_KEYWORDS_FILE="pinterest_keywords.txt"

# Optional: Official Pinterest API v5 Access Token or session cookie
# PINTEREST_ACCESS_TOKEN="pina_..."
# PINTEREST_SESSION_COOKIE="_pinterest_sess=..."

# YouTube Filtering Settings
MIN_DURATION_MINUTES=20
MAX_VIDEO_AGE_DAYS=30
ALLOW_SHORTS=false
ALLOW_LIVESTREAMS=false
```

### Editing Pinterest Keywords

You can add, edit, or remove search keywords without modifying Python source code by editing `pinterest_keywords.txt` directly:

```text
aesthetic nature videos
nature aesthetic 4k
dreamy nature aesthetic
cinematic nature scenery
peaceful nature clips
aesthetic sunset nature
pink sunset aesthetic
golden hour nature
mountain sunset aesthetic
blue sky clouds aesthetic
river flowing nature aesthetic
waterfall aesthetic video
ocean waves aesthetic
forest road aesthetic
flowers field aesthetic
wildflowers nature aesthetic
moon night aesthetic nature
misty mountains aesthetic
lake mountain scenery
autumn nature aesthetic
winter night nature aesthetic
nature b roll vertical
nature aesthetic video 9:16
relaxing nature scenery video
moody nature aesthetic
```

---

## 5. Google Drive API Setup

Use either a **Service Account** (recommended for headless servers) or **OAuth 2.0 Client ID** (for personal Google Drive).

1. Share your target Google Drive folder with the Service Account email as **Editor**.
2. Set `GOOGLE_DRIVE_FOLDER_ID` in `.env` to the target folder ID.
3. Configure `GOOGLE_SERVICE_ACCOUNT_FILE="service_account.json"`.

---

## 6. CLI Usage

### Basic Run (All enabled sources)
```bash
python main.py
```

### Dry Run (Test discovery & selection without downloading or uploading)
```bash
python main.py --dry-run
```

### Filter by Source
Run only YouTube:
```bash
python main.py --source youtube
```

Run only Pinterest:
```bash
python main.py --source pinterest
```

Run only Instagram Trending Audio:
```bash
python main.py --source instagram
```

Run all sources:
```bash
python main.py --source all
```

### Limit Number of Videos
Download exactly 2 videos:
```bash
python main.py --limit 2
```

### View Database Status
```bash
python main.py --status
```

### Retry Failed Videos
Reset failed records to `DISCOVERED`:
```bash
python main.py --retry-failed
```

---

## 7. Execution Summary Report

At the end of every run, PodFetch logs an actual execution summary:

```text
PODFETCH SUMMARY

YouTube candidates: 60
Pinterest candidates: 0
Duplicates skipped: 22
Eligible videos: 38
Selected: 1
Downloaded: 1
Uploaded to Google Drive: 1
Failed: 0
```

---

## 8. Running the Test Suite

Run the complete test suite:

```bash
pytest -v
```

All 38 test cases validate:
- Pinterest search-result parsing and media extraction
- Video versus static image detection
- Keyword relevance and cross-keyword deduplication
- Mixed YouTube + Pinterest candidate selection
- Missing metadata handling
- FFprobe media validation
- Download failure backoff and recovery
- Drive upload failure isolation
- Database schema migration & `(platform, source_id)` uniqueness
- Dry-run mode non-destructiveness
