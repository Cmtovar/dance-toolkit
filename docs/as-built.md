# Dance Toolkit — As-Built (through Phase 4)

How the project was actually built, as of 2026-04-30. For the original design intent, see [dance-toolkit-design.md](dance-toolkit-design.md). For significant deviations, see [dance-toolkit-addendum-01.md](dance-toolkit-addendum-01.md).

---

## Architecture (actual)

```
Phone / Laptop (browser)              Raspberry Pi 4B
┌──────────────────────────┐         ┌──────────────────────┐
│  Dance Toolkit UI        │         │  Toolkit API (:8091) │
│  (Svelte + Tailwind)     │◄──────► │  (Python stdlib HTTP)│
│                          │Tailscale│                      │
│  - YouTube iframe embed  │         │  - SQLite metadata   │
│  - HTML5 <video> player  │         │  - yt-dlp download   │
│  - CSS mirror (default)  │         │  - OAuth token serve │
│  - IndexedDB video store │         │  - Static file serve │
│  - MediaRecorder capture │         │                      │
│  - Direct YouTube upload │         │                      │
└──────────────────────────┘         └──────────────────────┘
         │
         │ (opt-in, per recording)
         ▼
   ┌──────────┐
   │ YouTube   │
   │ (unlisted)│
   └──────────┘
```

### What lives where

| Component | Location | Why |
|-----------|----------|-----|
| Video playback + speed control | Browser (HTML5 `playbackRate` or YouTube iframe API) | Full speed range client-side, no Pi bottleneck |
| Routine video cache | Browser (IndexedDB, `routines` store) | Downloaded once from Pi, plays locally forever |
| Recorded attempt videos | Browser (IndexedDB, `attempts` store) | Instant save, no round-trip to Pi |
| Move/routine/attempt metadata | Pi (SQLite) | Tiny, self-hosted, private |
| Video download (yt-dlp) | Pi | One-time per routine, result cached on client |
| YouTube OAuth tokens | Pi (token.json) | Pi refreshes tokens, serves access_token to client via API |
| YouTube upload execution | Browser (fetch to googleapis.com) | Client uploads directly using token from Pi |
| Static frontend files | Pi (built Svelte app in `static/`) | Served by Python HTTP server |

---

## Tech Stack (actual)

| Component | Technology | Notes |
|-----------|-----------|-------|
| Backend | Python stdlib (`http.server`) | No external dependencies, threaded |
| Database | SQLite | Single file, PRAGMA foreign_keys |
| Frontend | Svelte 5 + Tailwind CSS + Vite | Runes syntax ($state, $props, $effect, $bindable) |
| Video download | yt-dlp | Single file download, no ffmpeg post-processing |
| YouTube upload | Client-side fetch to YouTube Data API v3 | Resumable upload protocol, uses OAuth token from Pi |
| Video playback | YouTube iframe API + HTML5 `<video>` | YouTube: 0.25x–2x; HTML5: 0.05x–4x |
| Video storage | IndexedDB (two object stores) | `attempts` for recordings, `routines` for cached downloads |
| Recording | `getUserMedia()` + `MediaRecorder` | VP9/VP8/MP4 codec negotiation |
| Mirroring | CSS `transform: scaleX(-1)` | Applied to video element/iframe, on by default |
| Hosting | systemd user service on Pi | Port 8091, Tailscale access only |

---

## Pi Directory Structure (actual)

```
~/services/dance-toolkit/
├── server.py                    # Python stdlib HTTP server
├── setup_youtube_oauth.py       # One-time OAuth setup script
├── database.db                  # SQLite metadata
├── token.json                   # YouTube OAuth token (after setup)
├── client_secret.json           # Google OAuth client credentials (after setup)
├── videos/                      # yt-dlp downloads (one MP4 per routine)
│   └── <routine-id>.mp4
└── static/                      # Built Svelte frontend
    ├── index.html
    └── assets/
        ├── index-*.js
        └── index-*.css
```

Note: `speeds/` directory exists on Pi from Phase 3 (now obsolete, can be cleaned up). `overflow/` directory no longer created.

---

## Data Model (actual)

```
Routine
├── id: INTEGER PRIMARY KEY
├── name: TEXT                          # initially set to YouTube video ID
├── created: TEXT (datetime)
│
├── Alternate[]
│   ├── id: INTEGER PRIMARY KEY
│   ├── routine_id → routines(id) CASCADE
│   ├── youtube_url: TEXT
│   ├── label: TEXT
│   ├── is_mirrored: INTEGER (0/1)
│   ├── notes: TEXT
│   └── sort_order: INTEGER
│
├── Move[]
│   ├── id: INTEGER PRIMARY KEY
│   ├── routine_id → routines(id) CASCADE
│   ├── alternate_id → alternates(id) SET NULL
│   ├── name: TEXT                      # auto-generated "segment-<timestamp>"
│   ├── start_time: REAL
│   ├── end_time: REAL
│   ├── max_clean_speed: REAL (default 1.0)
│   ├── status: TEXT (learning|practicing|solid|mastered)
│   ├── last_drilled: TEXT
│   ├── drill_count: INTEGER
│   ├── sort_order: INTEGER
│   │
│   └── Attempt[]
│       ├── id: INTEGER PRIMARY KEY
│       ├── move_id → moves(id) CASCADE
│       ├── youtube_url: TEXT (null until uploaded)
│       ├── mime_type: TEXT (default 'video/webm')
│       ├── upload_status: TEXT (pending|on_youtube)
│       ├── recorded: TEXT (datetime)
│       └── notes: TEXT                 # user-given name, optional
│
└── timing_floor: REAL                  # computed: min of all moves' max_clean_speed
```

---

## API Endpoints (actual)

Base URL: `http://100.97.40.66:8091`

### Routines
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/routines` | List all routines with move_count, solid_count, timing_floor |
| POST | `/api/routines` | Create routine (+ optional first alternate from youtube_url) |
| GET | `/api/routines/:id` | Full routine with alternates, moves, and attempts nested |
| PUT | `/api/routines/:id` | Update routine name |
| DELETE | `/api/routines/:id` | Delete routine (cascades to alternates, moves, attempts) |

### Alternates
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/routines/:id/alternates` | Add alternate performance URL |
| PUT | `/api/routines/:id/alternates/:aid` | Update alternate metadata |
| DELETE | `/api/routines/:id/alternates/:aid` | Remove alternate |

### Moves
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/routines/:id/moves` | Create move (name, start_time, end_time, alternate_id) |
| PUT | `/api/routines/:id/moves/:mid` | Update move (speed, status, timestamps) |
| DELETE | `/api/routines/:id/moves/:mid` | Delete move |
| POST | `/api/routines/:id/moves/:mid/drill` | Increment drill_count, set last_drilled |

### Attempts
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/routines/:id/moves/:mid/attempts` | Create attempt metadata (no video — client stores in IndexedDB) |
| GET | `/api/routines/:id/moves/:mid/attempts` | List attempts for a move |
| DELETE | `/api/routines/:id/moves/:mid/attempts/:aid` | Delete attempt metadata |
| PUT | `/api/attempts/:id` | Update attempt (notes, youtube_url, upload_status) |
| GET | `/api/attempts` | All attempts across all routines with move/routine context |

### Video
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/routines/:id/download-video` | Trigger yt-dlp download on Pi (background thread) |
| GET | `/api/routines/:id/video/status` | Download status + file availability |
| GET | `/api/routines/:id/video` | Serve video file (range requests supported) |

### YouTube OAuth
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/youtube/token` | Fresh OAuth access_token for client-side YouTube upload |

### Health
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Service health check (for My Fold Pods integration) |

---

## Frontend Components

### App.svelte
Router. Four views: `home` (URL input), `player` (main workspace), `history` (routine list), `recordings` (all attempts portal). Header nav with links to recordings and history.

### UrlInput.svelte
Text input that accepts YouTube URLs or video IDs. Extracts video ID, passes to parent.

### Player.svelte
The main workspace — everything happens here. Contains:
- **Video player**: YouTube iframe (0.25x–2x) or HTML5 `<video>` from IndexedDB cache (0.05x–4x), switchable
- **Timeline**: Interactive scrubbing bar with marker segments, color-coded by speed, pointer-capture scrubbing
- **Playback controls**: Play/pause, ±5s skip, add marker
- **SpeedControl**: Slider + presets + ±0.05 nudge, range adapts to video source
- **Segment list**: All markers with timestamps, speed bars, delete buttons
- **Attempt section**: Per-segment recording + review. Shows recorder, attempt list with inline naming/upload/delete, inline video playback
- **Video source toggle**: Download routine video via Pi's yt-dlp, cache in IndexedDB, switch between YouTube and local
- **Mirror toggle**: On by default, button to flip

### SpeedControl.svelte
Reusable speed control with slider, preset buttons, and ±0.05 nudge buttons. Two preset sets: base (0.25–2x for YouTube) and extended (0.05–4x for local video).

### Recorder.svelte
Camera recording component. States: idle → requesting → ready → recording → saving. Uses `getUserMedia` for camera/mic, `MediaRecorder` for capture. Saves blob to IndexedDB and metadata to Pi. No automatic upload — recording is purely local.

### Recordings.svelte
All-attempts portal. Flat chronological list of every recording across all routines. Each entry shows: optional user-given name, date, routine name (clickable to navigate), segment timestamp. Actions: play inline, rename, upload to YouTube, delete.

### History.svelte
Routine list with YouTube thumbnails, segment count, timing floor. Click to open in player. Delete with confirmation.

### api.ts
API client module. All fetch calls to Pi endpoints. Also contains `uploadToYouTube()` which fetches an OAuth token from Pi then does a resumable upload directly to YouTube's API.

### videoStore.ts
IndexedDB wrapper. Two object stores in `dance-toolkit-videos` (version 2):
- `attempts`: recorded video blobs keyed by attempt ID
- `routines`: cached routine video blobs keyed by routine ID

---

## User Flow (actual)

1. Open Dance Toolkit (URL or via My Fold Pods WebView)
2. Paste a YouTube URL → video loads mirrored, starts playing
3. While watching, tap "marker" to divide the song at move transitions
4. Adjust speed per segment — slow down hard parts, leave easy parts at 1x
5. Routine auto-creates on first marker (named after video ID)
6. Optionally: download video for full 0.05x–4x speed range (yt-dlp on Pi → cached in IndexedDB)
7. Select a segment → tap "record" to capture yourself practicing
8. Recording saves instantly to IndexedDB, playable immediately
9. Optionally: name the recording, upload to YouTube
10. "Recordings" portal shows all recordings across all routines
11. "History" shows all routines with progress summary

---

## Phase Build History

### Phase 1 — Core Player (commit e3fefa5)
YouTube embed with speed control (0.25x–2x, 5% nudge), mirrored by default, URL input, mobile-first.

### Phase 2 — Clip Farm (commit 538c4ed)
Marker-based segmentation, per-segment speed, timeline visualization, segment list, history view, routine auto-creation, alternates.

### Phase 3 — Speed Tiers (commit dfbb5fd)
Originally: yt-dlp + ffmpeg to generate 5 speed tier files per routine, auto-tier-selection, HTML5 video playback.
**Replaced in Phase 4** with single yt-dlp download + HTML5 `playbackRate`.

### Phase 4 — Attempt Recording + Client-Side Video (commit 299b1b0)
- Rewrote video handling: single download, IndexedDB cache, `playbackRate` for all speeds
- Browser camera recording via `getUserMedia` + `MediaRecorder`
- IndexedDB as primary video store for both recordings and routine cache
- YouTube upload: opt-in, client-direct (Pi serves OAuth token only)
- Recordings portal for browsing all attempts
- Inline naming for recordings
- Removed: ffmpeg speed tiers, Pi video relay, Pi upload queue, overflow directory
