# Dance Toolkit — Design Addendum 01

Significant deviations from [dance-toolkit-design.md](dance-toolkit-design.md) discovered during Phases 1–4 build. These decisions were made based on real usage and should inform future phases.

---

## 1. Pi is not a video server

**Design doc assumed:** Pi serves speed tier files, receives and stores recorded videos, relays uploads to YouTube, holds overflow clips.

**What happened:** Pi is too slow for video I/O. Serving video over Tailscale from the Pi introduced painful wait times. Downloading, transcoding, and serving multiple speed tier files (5 per routine, ~200MB total) took 10+ minutes of generation time and strained the 28GB storage.

**Decision:** All video lives client-side. Pi handles only metadata (JSON) and OAuth tokens. The client (phone/laptop browser) stores video in IndexedDB, which has access to the device's full storage (typically 50-80% of free disk space, tens of GB on the Pixel 10 Pro Fold).

**Impact on future phases:**
- Phase 6 (Device Sync): Video won't sync between devices through the Pi. Each device holds its own recordings in IndexedDB. Shared state is metadata only (which move, which speed, play/pause). If a recording needs to be on both devices, YouTube is the bridge.
- Phase 7 (Compare): Side-by-side compare will use locally cached video, not Pi-served files. Both the instructor clip and the attempt must be in the device's IndexedDB.

---

## 2. Speed tiers replaced by HTML5 playbackRate

**Design doc assumed:** Pre-generated speed tier files (0.25x, 0.5x, 0.75x, 0.85x, 1x) via yt-dlp + ffmpeg on Pi. App auto-selects base file and uses iframe playbackRate on top for fine-grained control. Effective range ~0.125x through high multipliers.

**What happened:** HTML5 `<video>` element's `playbackRate` property handles 0.05x–4.0x directly on a single file. No pre-generation needed, no tier selection logic, no ffmpeg dependency. One yt-dlp download (~30MB) replaces five transcoded files (~200MB).

**Decision:** Single video file downloaded by yt-dlp on Pi, cached in IndexedDB on client. All speed variation via `playbackRate`. YouTube iframe API still used for YouTube-mode playback (0.25x–2x range), with a toggle to switch to local cached video for the full range.

**What this means:** The Speed Tiers concept from the design doc is fully obsolete. The `speeds/` directory on Pi, the `SpeedTier[]` in the data model, and all `/api/routines/:id/speeds/*` endpoints are gone. The speed slider and nudge controls work the same from the user's perspective — the implementation underneath is just simpler.

---

## 3. YouTube upload is client-direct and opt-in

**Design doc assumed:** Record → client blob → Pi queues upload → YouTube returns ID → Pi stores URL → client releases blob. Overflow to Pi storage when quota hit. Fully automatic, zero-interruption pipeline.

**What happened:** Since video already lives client-side (IndexedDB), sending it to Pi just to relay to YouTube adds unnecessary latency and doubles the data transfer. The Pi's upload speed is also a bottleneck. More importantly, most practice recordings are throwaway reps — auto-uploading every take wastes quota and clutters the YouTube channel.

**Decision:**
- Recording saves to IndexedDB only. Immediately playable, no upload.
- User can name recordings and optionally upload specific ones to YouTube.
- Upload goes directly from client browser to YouTube's API using an OAuth access token fetched from Pi.
- Pi's role: store `token.json`, refresh when expired, serve fresh `access_token` via `GET /api/youtube/token`.

**Impact on future phases:**
- Upload queue and overflow concepts are eliminated. No `overflow/` directory, no drain-overnight strategy.
- Quota management shifts to the user — they choose what's worth uploading.
- The 6-uploads/day free tier limit is less of a concern since uploads are selective, not automatic.

---

## 4. Tech stack differs from design doc

**Design doc specified:** FastAPI (async, WebSocket support), Alpine.js or htmx (no build step), Podman container.

**What was built:**
- **Backend:** Python stdlib `http.server` with `ThreadingMixIn`. No external Python dependencies for the core server. Zero-install on any Python 3 system.
- **Frontend:** Svelte 5 with Tailwind CSS, built with Vite. Runes syntax (`$state`, `$props`, `$effect`, `$bindable`). Requires a build step but produces a small static bundle (~78KB JS, ~14KB CSS).
- **Hosting:** systemd user service, not a Podman container. Simpler to manage, no container overhead on the Pi's limited resources.

**Rationale:** stdlib server is sufficient for a single-user app. Svelte provides better reactivity for the complex player UI than Alpine/htmx would. No container needed for a simple Python process.

---

## 5. Recordings exist as a first-class view

**Design doc assumed:** Attempts are nested under moves, viewed in Practice Mode or via long-press on a move tile.

**What was built:** A dedicated "Recordings" portal accessible from the main nav. Shows all recordings across all routines chronologically. Each recording shows its routine/segment context and can be played, named, uploaded, or deleted. The user can also tap the routine name to navigate directly to that routine's player.

**Rationale:** The user wants a portal to find recordings in relation to one another — not buried under individual segments. Recordings are personal artifacts worth browsing on their own. No forced structure (no required categories, grouping, or filtering) — just a flat list with context visible.

---

## 6. Moves are not named by the user

**Design doc had:** `name: "chorus hit 1"` as a move field, implying user-facing naming.

**UX principles say:** "Don't ask the user to name moves. They don't know what the move is called — they don't know the move yet."

**What was built:** Move names are auto-generated (`segment-<timestamp>`) and never shown to the user. Segments are identified by their timestamp on the timeline. The user interacts with time boundaries, not named entities.

**Note:** Recordings (attempts) *can* be named — the user chooses to name them after the fact, when they know what they recorded and why it matters. This is the opposite of requiring a name upfront.

---

## Revised Phase Plan

Phases 1–4 are complete. The remaining phases from the design doc should be built with these realities in mind:

### Phase 5 — Progress Tracking + Drill Queue
Unchanged in concept. The data model already supports status, max_clean_speed, last_drilled, drill_count. This phase adds the UI: a drill queue view showing moves sorted by staleness, timing floor visibility, and status progression interface.

### Phase 6 — Device Sync
WebSocket sync between phone and laptop via Pi. Scope adjusted: sync is metadata-only (play, pause, speed, current position, mirror state, which segment). Video does not travel through the Pi — each device uses its own IndexedDB cache or YouTube embed. Recording commands can be sent from phone to trigger laptop's camera, but the recorded video stays on the recording device's IndexedDB.

### Phase 7 — Compare + Polish
Side-by-side instructor vs. attempt. Both videos must be available locally (IndexedDB) on the viewing device. Foldable-aware layout for unfolded Pro Fold. Offline metadata cache for transit use (metadata from Pi cached locally, video already in IndexedDB).
