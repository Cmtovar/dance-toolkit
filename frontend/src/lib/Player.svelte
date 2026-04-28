<script lang="ts">
  import { onMount } from 'svelte'
  import SpeedControl from './SpeedControl.svelte'
  import { api, type Routine, type Move } from './api'

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

  // Routine state — loaded or created from the video
  let routine = $state<Routine | null>(null)
  let markers = $state<Move[]>([])
  let activeSegmentIndex = $state(-1)
  let timeUpdateInterval: number

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
    // Poll current time for timeline
    timeUpdateInterval = setInterval(() => {
      if (player && playerReady) {
        currentTime = player.getCurrentTime()
        duration = player.getDuration() || duration
        // Auto-apply segment speed
        applySegmentSpeed()
      }
    }, 250)
    return () => {
      clearInterval(timeUpdateInterval)
      player?.destroy()
    }
  })

  async function loadRoutine() {
    // Check if a routine already exists for this video
    const routines = await api.listRoutines()
    const existing = routines.find((r: any) => {
      // Match by checking alternates
      return false // We'll match by routine source below
    })
    // Try to find by stored source_url
    for (const r of routines) {
      const full = await api.getRoutine(r.id)
      if (full.alternates?.some(a => a.youtube_url === sourceUrl || extractVideoId(a.youtube_url) === videoId)) {
        routine = full
        markers = (full.moves || []).sort((a, b) => a.start_time - b.start_time)
        return
      }
    }
    // No existing routine — that's fine, markers will be empty until the user adds them
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

  function applySegmentSpeed() {
    if (markers.length === 0) return
    const idx = findSegmentIndex(currentTime)
    if (idx !== activeSegmentIndex && idx >= 0 && idx < markers.length) {
      activeSegmentIndex = idx
      const segmentSpeed = markers[idx].max_clean_speed
      if (Math.abs(segmentSpeed - speed) > 0.01) {
        speed = segmentSpeed
        if (player && playerReady) {
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
    if (playerReady && player) {
      player.setPlaybackRate(speed)
    }
  })

  function togglePlay() {
    if (!player || !playerReady) return
    if (isPlaying) player.pauseVideo()
    else player.playVideo()
  }

  function skip(seconds: number) {
    if (!player || !playerReady) return
    player.seekTo(player.getCurrentTime() + seconds, true)
  }

  function seekTo(time: number) {
    if (!player || !playerReady) return
    player.seekTo(time, true)
  }

  async function addMarker() {
    if (!player || !playerReady) return
    const time = player.getCurrentTime()

    // Create routine if it doesn't exist yet
    if (!routine) {
      routine = await api.createRoutine({ name: videoId, youtube_url: sourceUrl })
      routine = await api.getRoutine(routine.id)
    }

    // Find where this marker fits
    const endTime = findNextMarkerTime(time)
    const move = await api.createMove(routine!.id, {
      name: `segment-${Date.now()}`,
      start_time: Math.round(time * 10) / 10,
      end_time: endTime,
      alternate_id: routine!.alternates?.[0]?.id,
    })

    // Update previous marker's end time if needed
    const prevIdx = findPrevMarkerIndex(time)
    if (prevIdx >= 0) {
      await api.updateMove(routine!.id, markers[prevIdx].id, {
        end_time: Math.round(time * 10) / 10,
      })
    }

    // Reload
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
      <div id={playerId} class="w-full h-full"></div>
    </div>
  </div>

  <!-- Timeline with markers -->
  {#if duration > 0}
    <div class="relative w-full h-12 bg-neutral-900 rounded-lg overflow-hidden">
      <!-- Segments colored by speed -->
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

      <!-- Playhead -->
      <div
        class="absolute top-0 w-0.5 h-full bg-white z-10 pointer-events-none"
        style:left="{timelinePercent(currentTime)}%"
      ></div>

      <!-- Time label -->
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

    <!-- Speed control (applies to current segment if markers exist) -->
    <SpeedControl
      bind:speed
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
  </div>
</div>
