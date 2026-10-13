# Quran Ayah Reel Builder (`quran/` module)

An automated short-form video generator ("islamic" feature) for PodFetch that builds aesthetic vertical reels (1080x1920 @ 60fps) from Quran recitations with Urdu translations and authentic Uthmani calligraphy.

---

## Architecture & Pipeline

The builder implements an 11-step sequential pipeline:

```
[Playlist / Video Source]
        │
        ▼ (Step 1-2: State & JIT Download)
[Single Video at next_index]
        │
        ▼ (Step 3: Whisper Extraction)
[Groq Whisper large-v3-turbo (verbose timestamps)]
        │
        ▼ (Step 4: Ayah Selection)
[Groq LLM (openai/gpt-oss-20b) Standalone Ayah Candidate]
        │
        ▼ (Step 5: Ayah Identification - Accuracy Critical)
[Local Tanzil Uthmani Text Match (assets/quran-uthmani.txt)]
        │
        ▼ (Step 6: Precision Audio Cut)
[Trimmed Recitation Audio (8-40s, 0.3s lead/tail fades)]
        │
        ▼ (Step 7: Background Discovery & Vetting)
[Pinterest Video / Fallback (Luma < 0.62, No Watermarks)]
        │
        ▼ (Step 8-10: Video Prep, Text Burn & Encode)
[FFmpeg: Noto Sans Arabic + Urdu + libx264 1080x1920@60fps]
        │
        ▼ (Step 11: Output & Cloud Sync)
[ready/reel_YYYY-MM-DD.mp4 + ready/manifest.json -> Google Drive]
```

---

## 1. Installation & Requirements

Ensure system packages and fonts are installed:

```bash
# Ubuntu / Debian
sudo apt-get update
sudo apt-get install -y ffmpeg fonts-noto-core fonts-noto-cjk

# Python dependencies
pip install -r requirements.txt
```

Core dependencies include:
- `yt-dlp>=2024.0.0`
- `requests>=2.31.0`
- `pillow>=10.0.0`
- `fastapi`, `google-api-python-client`, `google-auth`

---

## 2. Environment Variables

Configure your `.env` file with Groq and Google Drive credentials:

```ini
# Groq API Keys (Automatic rotation supported)
GROQ_API_KEY=gsk_...
GROQ_API_KEY_2=gsk_...
GROQ_API_KEY_3=gsk_...
GROQ_API_KEY_4=gsk_...

# YouTube Quran Playlist URL (Default for sequential runs)
QURAN_PLAYLIST_URL=https://www.youtube.com/playlist?list=...

# Google Drive Sync (Optional - automatically backed up if present)
GOOGLE_DRIVE_FOLDER_ID=15KIAIk-rVAr4A1Ow5A2zeCXyA5WaB41j
```

---

## 3. First-Run Tanzil Text Setup

The authentic Tanzil Uthmani text (`assets/quran-uthmani.txt`, 6,236 verses) and Fateh Muhammad Jalandhry Urdu translation (`assets/quran-urdu.txt`) are bundled locally within `assets/` and `quran/assets/`.

On first run, if files are absent, the database manager automatically fetches and verifies them from `tanzil.net/download`:

```python
from quran.tanzil import get_tanzil_db
db = get_tanzil_db()
print(f"Loaded {len(db.verses)} verses across 114 surahs.")
```

> **Critical Rule**: On-screen Arabic script **NEVER** originates from speech recognition transcription. It is strictly resolved from the Tanzil Uthmani database with complete diacritics and tashkeel.

---

## 4. CLI Usage

### Dry-Run / Self-Test (Steps 1–5 without rendering)

Evaluates audio extraction, Whisper transcription, Groq LLM selection, and Tanzil fuzzy-matching without encoding video:

```bash
python -m quran.build --date 2026-10-13 --dry-run
```

You can test a specific video URL directly:

```bash
python -m quran.build --date 2026-10-13 --dry-run --video "https://www.youtube.com/watch?v=ziiGEfsWrjg"
```

### Full Production Build

Executes the full pipeline, burns multi-layer typography, encodes at 1080x1920@60fps, generates deliverables in `ready/`, and syncs to Google Drive:

```bash
python -m quran.build --date 2026-10-13
```

---

## 5. Output Deliverables & Format

When a build succeeds with exit code `0`, the following files are produced in `ready/`:

1. `ready/reel_YYYY-MM-DD.mp4`:
   - Resolution: `1080x1920` (vertical 9:16)
   - Framerate: `60 fps`
   - Video Bitrate: `15 Mbps` (`-b:v 15M -maxrate 20M -bufsize 40M`)
   - Audio: `AAC 128 kbps` (`+faststart`)
   - Visual: Arabic Uthmani text placed above Urdu translation (`y=(h-text_h)/2-200`), white with subtle black drop shadow, no bounding box.

2. `ready/manifest.json`:
   ```json
   {
     "reel_file": "ready/reel_2026-10-13.mp4",
     "date": "2026-10-13",
     "surah_number": 1,
     "ayah_number": 1,
     "ayah_end": null,
     "surah_name_english": "Al-Fatihah",
     "surah_name_arabic": "الفاتحة",
     "arabic_text": "بِسْمِ ٱللَّهِ ٱلرَّحْمَٰنِ ٱلرَّحِيمِ",
     "urdu_translation": "شروع الله کا نام لے کر جو بڑا مہربان نہایت رحم والا ہے",
     "caption": "In the name of Allah, the Most Compassionate, the Most Merciful.",
     "hashtags": [
       "#Quran",
       "#Islam",
       "#AyahOfTheDay"
     ],
     "duration_seconds": 9.38,
     "drive_file_id": "15KIAIk-rVAr4A1Ow5A2zeCXyA5WaB41j",
     "drive_link": "https://drive.google.com/file/d/15KIAIk-rVAr4A1Ow5A2zeCXyA5WaB41j/view",
     "created_at": "2026-10-13T17:58:31.310263+00:00"
   }
   ```

---

## 6. Strict Contract Guarantees

- **No Em-Dash (`—` / `–`)**: Zero em-dash characters are allowed in any user-facing text, subtitles, or captions.
- **Exactly 3 Hashtags**: Every manifest strictly enforces 3 hashtags.
- **English Caption**: Meaningful spiritual English caption accompanying the Ayah.
- **No-Reuse Guarantee**:
  - Ayahs are recorded in `state.json` under `used_ayahs` and never repeated.
  - Background video Drive IDs and Pin IDs are recorded under `used_background_drive_ids` and `used_background_pin_ids` and never reused.
- **Strict Playlist Order**: Progression is tracked by `next_index` in `state.json` with no bulk downloading.

---

## 7. Troubleshooting

### YouTube Bot Checks & Cookies
If YouTube blocks extraction with `Sign in to confirm you're not a bot`, configure a cookies file:
```bash
yt-dlp --cookies-from-browser chrome ...
```
Or export your session to `cookies.txt` and reference it in `PlaylistFetcher` options.

### Whisper Language Hints (`ar` / `ur`)
The Whisper audio transcription passes `language="ar"` and `"language_hints=['ar', 'ur']"` to prompt accurate multilingual phonetics for both the Arabic recitation and subsequent Urdu translation.
