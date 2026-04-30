<script lang="ts">
  import { onMount } from 'svelte'
  import SpeedControl from './SpeedControl.svelte'
  import Recorder from './Recorder.svelte'
  import { api, type Routine, type Move, type Attempt } from './api'
  import { getVideo, deleteVideo, getRoutineVideo, saveRoutineVideo } from './videoStore'

  let { videoId, sourceUrl, onBack }: {
    videoId: string
    sourceUrl: string
    onBack: () => void
  } = $props()

  let player: YT.Player | null = null
  let playerReady = $state(false)
  let mirrored = $state(true)
  let speed = $state(1.0)
  let isPlaying = $state(false)
  let currentTime = $state(0)
  let duration = $state(0)
  const playerId = 'yt-player-' + Math.random().toString(36).slice(2)

  // Routine state
  let routine = $state<Routine | null>(null)
  let markers = $state<Move[]>([])
  let activeSegmentIndex = $state(-1)
  let timeUpdateInterval: number

  // Attempt playback state
  let reviewingAttempt = $state<Attempt | null>(null)

  // Local video state (single cached file, client-side playbackRate for all speeds)
  let useLocalVideo = $state(false)
  let localVideoUrl = $state<string | null>(null)
  let videoEl = $state<HTMLVideoElement | null>(null)
  let downloadStatus = $state<string>('idle')
  let downloadError = $state<string | null>(null)
  let downloadPollInterval: number | undefined

  declare global {
    interface Window {
      onYouTubeIframeAPIReady: () => void
      YT: typeof YT
    }
  }

  function loadYTApi(): Promise<void> {
    if (window.YT && window.YT.Player) return Promise.resolve()
    return new Promise((resolve) => {
      const prev = window.onYouTubeIframeAPIReady
      window.onYouTubeIframeAPIReady = () => {
        prev?.()
        resolve()
      }
      if (!document.querySelector('script[src*="youtube.com/iframe_api"]')) {
        const tag = document.createElement('script')
        tag.src = 'https://www.youtube.com/iframe_api'
        document.head.appendChild(tag)
      }
    })
  }

  function createPlayer() {
    if (player) {
      player.destroy()
      player = null
      playerReady = false
    }
    player = new window.YT.Player(playerId, {
      videoId,
      playerVars: {
        autoplay: 1,
        modestbranding: 1,
        rel: 0,
        playsinline: 1,
      },
      events: {
        onReady: () => {
          playerReady = true
          player!.setPlaybackRate(speed)
          duration = player!.getDuration()
          isPlaying = true
        },
        onStateChange: (e: YT.OnStateChangeEvent) => {
          isPlaying = e.data === window.YT.PlayerState.PLAYING
        },
      },
    })
  }

  onMount(() => {
    loadYTApi().then(createPlayer)
    loadRoutine()
    timeUpdateInterval = setInterval(() => {
      if (useLocalVideo) return
      if (player && playerReady) {
        currentTime = player.getCurrentTime()
        duration = player.getDuration() || duration
        applySegmentSpeed()
      }
    }, 250)
    return () => {
      clearInterval(timeUpdateInterval)
      if (downloadPollInterval) clearInterval(downloadPollInterval)
      if (localVideoUrl) URL.revokeObjectURL(localVideoUrl)
      player?.destroy()
    }
  })

  async function loadRoutine() {
    const routines = await api.listRoutines()
    for (const r of routines) {
      const full = await api.getRoutine(r.id)
      if (full.alternates?.some(a => a.youtube_url === sourceUrl || extractVideoId(a.youtube_url) === videoId)) {
        routine = full
        markers = (full.moves || []).sort((a, b) => a.start_time - b.start_time)
        await checkLocalVideo()
        return
      }
    }
  }

  function extractVideoId(url: string): string | null {
    try {
      const u = new URL(url)
      if (u.hostname === 'youtu.be') return u.pathname.slice(1)
      if (u.hostname.includes('youtube.com')) return u.searchParams.get('v')
    } catch {
      if (/^[a-zA-Z0-9_-]{11}$/.test(url)) return url
    }
    return null
  }

  // --- Local video (cached in IndexedDB, playbackRate for all speeds) ---

  async function checkLocalVideo() {
    if (!routine) return
    // Check IndexedDB cache first
    const cached = await getRoutineVideo(routine.id)
    if (cached) {
      localVideoUrl = URL.createObjectURL(cached)
      switchToLocalVideo()
      return
    }
    // Check if Pi has it downloaded
    const status = await api.videoStatus(routine.id)
    downloadStatus = status.status
    downloadError = status.error
    if (status.available) {
      // Pi has it — fetch once and cache in IndexedDB
      await cacheVideoFromPi()
    }
  }

  async function triggerDownload() {
    if (!routine) return
    await api.downloadVideo(routine.id)
    downloadStatus = 'downloading'
    startDownloadPolling()
  }

  function startDownloadPolling() {
    if (downloadPollInterval) return
    downloadPollInterval = setInterval(async () => {
      if (!routine) return
      const status = await api.videoStatus(routine.id)
      downloadStatus = status.status
      downloadError = status.error
      if (status.status === 'complete' || status.status === 'error' || status.status === 'idle') {
        clearInterval(downloadPollInterval)
        downloadPollInterval = undefined
        if (status.available) {
          await cacheVideoFromPi()
        }
      }
    }, 3000)
  }

  async function cacheVideoFromPi() {
    if (!routine) return
    downloadStatus = 'caching'
    try {
      const blob = await api.fetchVideoBlob(routine.id)
      await saveRoutineVideo(routine.id, blob)
      localVideoUrl = URL.createObjectURL(blob)
      switchToLocalVideo()
      downloadStatus = 'complete'
    } catch (e: any) {
      downloadError = e.message || 'Failed to cache video'
      downloadStatus = 'error'
    }
  }

  function switchToLocalVideo() {
    if (!localVideoUrl) return
    if (player && playerReady) {
      currentTime = player.getCurrentTime()
      player.destroy()
      player = null
      playerReady = false
    }
    useLocalVideo = true
  }

  function switchToYouTube() {
    const savedTime = currentTime
    useLocalVideo = false
    setTimeout(() => {
      createPlayer()
      if (player) {
        const checkReady = setInterval(() => {
          if (playerReady && player) {
            player.seekTo(savedTime, true)
            clearInterval(checkReady)
          }
        }, 200)
      }
    }, 100)
  }

  // --- Playback controls ---

  function applySegmentSpeed() {
    if (markers.length === 0) return
    const idx = findSegmentIndex(currentTime)
    if (idx !== activeSegmentIndex && idx >= 0 && idx < markers.length) {
      activeSegmentIndex = idx
      const segmentSpeed = markers[idx].max_clean_speed
      if (Math.abs(segmentSpeed - speed) > 0.01) {
        speed = segmentSpeed
        if (useLocalVideo && videoEl) {
          videoEl.playbackRate = speed
        } else if (player && playerReady) {
          player.setPlaybackRate(speed)
        }
      }
    }
  }

  function findSegmentIndex(time: number): number {
    for (let i = markers.length - 1; i >= 0; i--) {
      if (time >= markers[i].start_time) return i
    }
    return -1
  }

  $effect(() => {
    if (useLocalVideo && videoEl) {
      videoEl.playbackRate = speed
    } else if (playerReady && player) {
      player.setPlaybackRate(speed)
    }
  })

  function togglePlay() {
    if (useLocalVideo) {
      if (!videoEl) return
      if (videoEl.paused) { videoEl.play(); isPlaying = true }
      else { videoEl.pause(); isPlaying = false }
      return
    }
    if (!player || !playerReady) return
    if (isPlaying) player.pauseVideo()
    else player.playVideo()
  }

  function skip(seconds: number) {
    if (useLocalVideo && videoEl) {
      videoEl.currentTime += seconds
      return
    }
    if (!player || !playerReady) return
    player.seekTo(player.getCurrentTime() + seconds, true)
  }

  function seekTo(time: number) {
    if (useLocalVideo && videoEl) {
      videoEl.currentTime = time
      return
    }
    if (!player || !playerReady) return
    player.seekTo(time, true)
  }

  function onLocalTimeUpdate() {
    if (!videoEl) return
    currentTime = videoEl.currentTime
    duration = videoEl.duration || 0
    applySegmentSpeed()
  }

  // --- Markers ---

  async function addMarker() {
    const time = useLocalVideo && videoEl ? videoEl.currentTime : (player && playerReady ? player.getCurrentTime() : null)
    if (time === null) return

    if (!routine) {
      routine = await api.createRoutine({ name: videoId, youtube_url: sourceUrl })
      routine = await api.getRoutine(routine.id)
    }

    const endTime = findNextMarkerTime(time)
    await api.createMove(routine!.id, {
      name: `segment-${Date.now()}`,
      start_time: Math.round(time * 10) / 10,
      end_time: endTime,
      alternate_id: routine!.alternates?.[0]?.id,
    })

    const prevIdx = findPrevMarkerIndex(time)
    if (prevIdx >= 0) {
      await api.updateMove(routine!.id, markers[prevIdx].id, {
        end_time: Math.round(time * 10) / 10,
      })
    }

    routine = await api.getRoutine(routine!.id)
    markers = (routine!.moves || []).sort((a, b) => a.start_time - b.start_time)
  }

  function findNextMarkerTime(time: number): number {
    for (const m of markers) {
      if (m.start_time > time) return m.start_time
    }
    return duration || 999
  }

  function findPrevMarkerIndex(time: number): number {
    for (let i = markers.length - 1; i >= 0; i--) {
      if (markers[i].start_time < time) return i
    }
    return -1
  }

  async function removeMarker(moveId: number) {
    if (!routine) return
    await api.deleteMove(routine.id, moveId)
    routine = await api.getRoutine(routine.id)
    markers = (routine!.moves || []).sort((a, b) => a.start_time - b.start_time)
  }

  async function setSegmentSpeed(moveId: number, newSpeed: number) {
    if (!routine) return
    await api.updateMove(routine.id, moveId, { max_clean_speed: newSpeed })
    routine = await api.getRoutine(routine.id)
    markers = (routine!.moves || []).sort((a, b) => a.start_time - b.start_time)
  }

  function formatTime(seconds: number): string {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  function timelinePercent(time: number): number {
    if (!duration) return 0
    return (time / duration) * 100
  }

  // --- Attempt helpers ---

  let attemptBlobUrls = $state<Record<number, string>>({})
  let editingAttemptId = $state<number | null>(null)
  let editingNotes = $state('')
  let uploadingAttemptId = $state<number | null>(null)

  function activeSegmentAttempts(): Attempt[] {
    if (activeSegmentIndex < 0 || !markers[activeSegmentIndex]) return []
    return markers[activeSegmentIndex].attempts || []
  }

  async function onAttemptRecorded(attempt: Attempt) {
    if (!routine) return
    await loadAttemptBlob(attempt.id)
    routine = await api.getRoutine(routine.id)
    markers = (routine!.moves || []).sort((a, b) => a.start_time - b.start_time)
    reviewingAttempt = attempt
  }

  async function loadAttemptBlob(attemptId: number) {
    if (attemptBlobUrls[attemptId]) return
    const blob = await getVideo(attemptId)
    if (blob) {
      attemptBlobUrls[attemptId] = URL.createObjectURL(blob)
    }
  }

  async function deleteAttemptHandler(attemptId: number) {
    if (!routine || activeSegmentIndex < 0) return
    const move = markers[activeSegmentIndex]
    await api.deleteAttempt(routine.id, move.id, attemptId)
    await deleteVideo(attemptId)
    if (attemptBlobUrls[attemptId]) {
      URL.revokeObjectURL(attemptBlobUrls[attemptId])
      delete attemptBlobUrls[attemptId]
    }
    if (reviewingAttempt?.id === attemptId) reviewingAttempt = null
    routine = await api.getRoutine(routine.id)
    markers = (routine!.moves || []).sort((a, b) => a.start_time - b.start_time)
  }

  async function playAttempt(attempt: Attempt) {
    if (reviewingAttempt?.id === attempt.id) {
      reviewingAttempt = null
      return
    }
    await loadAttemptBlob(attempt.id)
    reviewingAttempt = attempt
  }

  function attemptVideoSrc(attempt: Attempt): string | null {
    return attemptBlobUrls[attempt.id] || null
  }

  function startEditingNotes(attempt: Attempt) {
    editingAttemptId = attempt.id
    editingNotes = attempt.notes || ''
  }

  async function saveNotes(attempt: Attempt) {
    await api.updateAttempt(attempt.id, { notes: editingNotes })
    editingAttemptId = null
    if (!routine) return
    routine = await api.getRoutine(routine.id)
    markers = (routine!.moves || []).sort((a, b) => a.start_time - b.start_time)
  }

  async function uploadAttemptToYouTube(attempt: Attempt) {
    uploadingAttemptId = attempt.id
    try {
      await loadAttemptBlob(attempt.id)
      const blob = await getVideo(attempt.id)
      if (!blob) throw new Error('Video not found locally')
      const title = attempt.notes || `attempt ${attempt.id}`
      const videoId = await api.uploadToYouTube(blob, title)
      await api.updateAttempt(attempt.id, {
        youtube_url: `https://www.youtube.com/watch?v=${videoId}`,
        upload_status: 'on_youtube',
      })
      if (!routine) return
      routine = await api.getRoutine(routine.id)
      markers = (routine!.moves || []).sort((a, b) => a.start_time - b.start_time)
    } catch (e: any) {
      alert(`Upload failed: ${e.message || 'unknown error'}`)
    } finally {
      uploadingAttemptId = null
    }
  }

  // --- Timeline scrubbing ---
  let isScrubbing = $state(false)
  let timelineEl: HTMLDivElement | null = null

  function scrubFromEvent(e: PointerEvent) {
    if (!timelineEl || !duration) return
    const rect = timelineEl.getBoundingClientRect()
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    seekTo(pct * duration)
  }

  function onTimelinePointerDown(e: PointerEvent) {
    isScrubbing = true
    timelineEl?.setPointerCapture(e.pointerId)
    scrubFromEvent(e)
  }

  function onTimelinePointerMove(e: PointerEvent) {
    if (!isScrubbing) return
    scrubFromEvent(e)
  }

  function onTimelinePointerUp() {
    isScrubbing = false
  }
</script>

<div class="w-full max-w-4xl flex flex-col gap-4">
  <button
    onclick={onBack}
    class="self-start text-neutral-400 hover:text-white transition-colors text-sm"
  >
    ← back
  </button>

  <!-- Video -->
  <div
    class="relative w-full bg-black rounded-lg overflow-hidden"
    style:transform={mirrored ? 'scaleX(-1)' : 'none'}
  >
    <div class="aspect-video">
      {#if useLocalVideo && localVideoUrl}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          bind:this={videoEl}
          src={localVideoUrl}
          class="w-full h-full"
          ontimeupdate={onLocalTimeUpdate}
          onplay={() => isPlaying = true}
          onpause={() => isPlaying = false}
          onloadedmetadata={() => { if (videoEl) duration = videoEl.duration }}
          playsinline
          autoplay
        ></video>
      {:else}
        <div id={playerId} class="w-full h-full"></div>
      {/if}
    </div>
  </div>

  <!-- Timeline with markers -->
  {#if duration > 0}
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div
      class="relative w-full h-12 bg-neutral-900 rounded-lg overflow-hidden cursor-pointer touch-none"
      bind:this={timelineEl}
      onpointerdown={onTimelinePointerDown}
      onpointermove={onTimelinePointerMove}
      onpointerup={onTimelinePointerUp}
      onpointercancel={onTimelinePointerUp}
    >
      {#each markers as marker, i}
        {@const left = timelinePercent(marker.start_time)}
        {@const nextTime = i < markers.length - 1 ? markers[i + 1].start_time : duration}
        {@const width = timelinePercent(nextTime) - left}
        {@const intensity = Math.max(0.2, Math.min(1, marker.max_clean_speed))}
        <div
          class="absolute top-0 h-full cursor-pointer border-r border-neutral-700 {activeSegmentIndex === i ? 'opacity-100' : 'opacity-60'}"
          style:left="{left}%"
          style:width="{width}%"
          style:background="rgba(255, 255, 255, {intensity * 0.15})"
          onclick={() => seekTo(marker.start_time)}
          role="button"
          tabindex="0"
          onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter') seekTo(marker.start_time) }}
          title="{formatTime(marker.start_time)} — {marker.max_clean_speed.toFixed(2)}x"
        >
          <span class="absolute bottom-0.5 left-1 text-[10px] text-neutral-400">{marker.max_clean_speed.toFixed(1)}x</span>
        </div>
      {/each}

      <div
        class="absolute top-0 w-0.5 h-full bg-white z-10 pointer-events-none"
        style:left="{timelinePercent(currentTime)}%"
      ></div>

      <span class="absolute top-1 right-2 text-[10px] text-neutral-500 z-10">
        {formatTime(currentTime)} / {formatTime(duration)}
      </span>
    </div>
  {/if}

  <!-- Controls -->
  <div class="flex flex-col gap-3 bg-neutral-900 rounded-lg p-4">
    <!-- Playback + marker -->
    <div class="flex items-center justify-center gap-4">
      <button
        onclick={() => skip(-5)}
        class="text-neutral-400 hover:text-white transition-colors px-2 py-1 text-sm"
      >
        -5s
      </button>
      <button
        onclick={togglePlay}
        class="w-12 h-12 flex items-center justify-center bg-white text-black rounded-full hover:bg-neutral-200 transition-colors"
      >
        {isPlaying ? '⏸' : '▶'}
      </button>
      <button
        onclick={() => skip(5)}
        class="text-neutral-400 hover:text-white transition-colors px-2 py-1 text-sm"
      >
        +5s
      </button>
      <button
        onclick={addMarker}
        class="text-sm px-3 py-1.5 rounded bg-neutral-800 text-neutral-300 hover:text-white hover:bg-neutral-700 transition-colors border border-neutral-700"
        title="Drop a marker at current time"
      >
        + marker
      </button>
    </div>

    <!-- Speed control -->
    <SpeedControl
      bind:speed
      minSpeed={useLocalVideo ? 0.05 : 0.25}
      maxSpeed={useLocalVideo ? 4.0 : 2.0}
      onSpeedChange={(s: number) => {
        if (activeSegmentIndex >= 0 && markers[activeSegmentIndex]) {
          setSegmentSpeed(markers[activeSegmentIndex].id, s)
        }
      }}
    />

    <!-- Segment list -->
    {#if markers.length > 0}
      <div class="flex flex-col gap-1 mt-1">
        <span class="text-xs text-neutral-500">Segments</span>
        {#each markers as marker, i}
          <div
            class="flex items-center gap-2 px-2 py-1 rounded text-sm {activeSegmentIndex === i ? 'bg-neutral-800' : ''}"
          >
            <button
              onclick={() => seekTo(marker.start_time)}
              class="font-mono text-xs text-neutral-400 hover:text-white w-10"
            >
              {formatTime(marker.start_time)}
            </button>
            <div class="flex-1 h-1 bg-neutral-700 rounded overflow-hidden">
              <div
                class="h-full bg-neutral-400 rounded"
                style:width="{Math.min(100, marker.max_clean_speed * 100)}%"
              ></div>
            </div>
            <span class="font-mono text-xs text-neutral-400 w-12 text-right">{marker.max_clean_speed.toFixed(2)}x</span>
            <button
              onclick={() => removeMarker(marker.id)}
              class="text-neutral-600 hover:text-red-400 text-xs"
            >
              ✕
            </button>
          </div>
        {/each}
      </div>
    {/if}

    <!-- Attempt recording + review -->
    {#if routine && activeSegmentIndex >= 0 && markers[activeSegmentIndex]}
      <div class="flex flex-col gap-2 pt-2 border-t border-neutral-800">
        <div class="flex items-center justify-between">
          <span class="text-xs text-neutral-500">
            Attempts for segment at {formatTime(markers[activeSegmentIndex].start_time)}
          </span>
          <Recorder
            routineId={routine.id}
            moveId={markers[activeSegmentIndex].id}
            onRecorded={onAttemptRecorded}
          />
        </div>

        {#if reviewingAttempt}
          {@const blobSrc = attemptVideoSrc(reviewingAttempt)}
          <div class="w-full aspect-video bg-black rounded-lg overflow-hidden relative">
            {#if blobSrc}
              <!-- svelte-ignore a11y_media_has_caption -->
              <video
                src={blobSrc}
                class="w-full h-full"
                controls
                playsinline
                autoplay
                style:transform={mirrored ? 'scaleX(-1)' : 'none'}
              ></video>
            {:else if reviewingAttempt.youtube_url}
              <iframe
                src="https://www.youtube.com/embed/{reviewingAttempt.youtube_url.split('v=')[1]}?autoplay=1&playsinline=1"
                class="w-full h-full"
                allow="autoplay"
                title="Attempt recording"
              ></iframe>
            {:else}
              <div class="w-full h-full flex items-center justify-center text-neutral-500 text-sm">
                Video not available on this device
              </div>
            {/if}
            <button
              onclick={() => reviewingAttempt = null}
              class="absolute top-2 right-2 bg-black/60 text-white rounded px-2 py-0.5 text-xs hover:bg-black/80"
            >
              close
            </button>
          </div>
        {/if}

        {#if activeSegmentAttempts().length > 0}
          <div class="flex flex-col gap-1">
            {#each activeSegmentAttempts() as attempt}
              <div class="flex flex-col gap-1 group">
                <div class="flex items-center gap-2 text-xs">
                  <button
                    onclick={() => playAttempt(attempt)}
                    class="flex-1 text-left px-2 py-1 rounded hover:bg-neutral-800 transition-colors {reviewingAttempt?.id === attempt.id ? 'bg-neutral-800 text-white' : 'text-neutral-400'}"
                  >
                    <span class="text-neutral-500">{new Date(attempt.recorded + 'Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</span>
                    {#if attempt.notes}
                      <span class="ml-1.5 text-neutral-300">{attempt.notes}</span>
                    {/if}
                  </button>
                  {#if attempt.upload_status === 'on_youtube'}
                    <span class="text-[10px] text-green-600">yt</span>
                  {:else if uploadingAttemptId === attempt.id}
                    <div class="w-3 h-3 border border-neutral-400 border-t-transparent rounded-full animate-spin"></div>
                  {:else}
                    <button
                      onclick={() => uploadAttemptToYouTube(attempt)}
                      class="text-[10px] text-neutral-600 hover:text-neutral-300 opacity-0 group-hover:opacity-100 transition-opacity"
                      title="Upload to YouTube"
                    >
                      yt↑
                    </button>
                  {/if}
                  <button
                    onclick={() => startEditingNotes(attempt)}
                    class="text-neutral-600 hover:text-neutral-300 opacity-0 group-hover:opacity-100 transition-opacity text-[10px]"
                    title="Name this recording"
                  >
                    ✎
                  </button>
                  <button
                    onclick={() => deleteAttemptHandler(attempt.id)}
                    class="text-neutral-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity text-xs"
                  >
                    x
                  </button>
                </div>
                {#if editingAttemptId === attempt.id}
                  <form
                    onsubmit={(e) => { e.preventDefault(); saveNotes(attempt) }}
                    class="flex items-center gap-1 px-2"
                  >
                    <input
                      type="text"
                      bind:value={editingNotes}
                      placeholder="name this recording..."
                      class="flex-1 bg-neutral-800 text-xs text-neutral-200 rounded px-2 py-1 border border-neutral-700 focus:border-neutral-500 outline-none"
                      autofocus
                    />
                    <button type="submit" class="text-xs text-neutral-400 hover:text-white">save</button>
                    <button type="button" onclick={() => editingAttemptId = null} class="text-xs text-neutral-600 hover:text-neutral-400">cancel</button>
                  </form>
                {/if}
              </div>
            {/each}
          </div>
        {/if}
      </div>
    {/if}

    <!-- Mirror + info row -->
    <div class="flex justify-between items-center">
      {#if markers.length > 0}
        <span class="text-xs text-neutral-500">
          {markers.length} segments
          {#if routine?.timing_floor != null}
            · floor: {routine.timing_floor.toFixed(2)}x
          {/if}
        </span>
      {:else}
        <span class="text-xs text-neutral-500">Drop markers to divide the song into moves</span>
      {/if}
      <button
        onclick={() => mirrored = !mirrored}
        class="text-xs px-3 py-1.5 rounded border transition-colors {mirrored
          ? 'border-neutral-600 text-neutral-300 bg-neutral-800'
          : 'border-neutral-700 text-neutral-500'}"
      >
        {mirrored ? 'mirrored' : 'original'}
      </button>
    </div>

    <!-- Local video (full speed range) -->
    {#if routine}
      <div class="flex items-center justify-between pt-2 border-t border-neutral-800">
        <div class="flex items-center gap-2">
          {#if localVideoUrl}
            <button
              onclick={() => useLocalVideo ? switchToYouTube() : switchToLocalVideo()}
              class="text-xs px-3 py-1.5 rounded border transition-colors {useLocalVideo
                ? 'border-blue-600 text-blue-300 bg-blue-900/30'
                : 'border-neutral-700 text-neutral-500 hover:text-neutral-300'}"
            >
              {useLocalVideo ? 'local video' : 'youtube'}
            </button>
            {#if useLocalVideo}
              <span class="text-[10px] text-neutral-500">0.05x–4x</span>
            {/if}
          {/if}
        </div>
        <div>
          {#if downloadStatus === 'idle' && !localVideoUrl}
            <button
              onclick={triggerDownload}
              class="text-xs px-3 py-1.5 rounded bg-neutral-800 text-neutral-400 hover:text-white hover:bg-neutral-700 transition-colors border border-neutral-700"
            >
              download for full speed range
            </button>
          {:else if downloadStatus === 'complete' && localVideoUrl}
            <span class="text-[10px] text-neutral-500">cached locally</span>
          {:else if downloadStatus === 'error'}
            <span class="text-[10px] text-red-400" title={downloadError || ''}>{downloadError?.slice(0, 40) || 'error'}</span>
          {:else if downloadStatus !== 'idle'}
            <span class="text-[10px] text-amber-400">{downloadStatus}...</span>
          {/if}
        </div>
      </div>
    {/if}
  </div>
</div>
