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

  // Speed tier state
  let speedTiers = $state<{ rate: number; size: number }[]>([])
  let tierStatus = $state<string>('idle')
  let tierError = $state<string | null>(null)
  let useLocalVideo = $state(false)
  let activeTierRate = $state(1.0)
  let videoEl = $state<HTMLVideoElement | null>(null)
  let tierPollInterval: number | undefined

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
      if (useLocalVideo) return
      if (player && playerReady) {
        currentTime = player.getCurrentTime()
        duration = player.getDuration() || duration
        // Auto-apply segment speed
        applySegmentSpeed()
      }
    }, 250)
    return () => {
      clearInterval(timeUpdateInterval)
      if (tierPollInterval) clearInterval(tierPollInterval)
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
        await loadSpeedTiers()
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
    if (useLocalVideo) {
      applyLocalSpeed(speed)
    } else if (playerReady && player) {
      player.setPlaybackRate(speed)
    }
  })

  function togglePlay() {
    if (useLocalVideo) return toggleLocalPlay()
    if (!player || !playerReady) return
    if (isPlaying) player.pauseVideo()
    else player.playVideo()
  }

  function skip(seconds: number) {
    if (useLocalVideo && videoEl) {
      videoEl.currentTime += seconds / activeTierRate
      return
    }
    if (!player || !playerReady) return
    player.seekTo(player.getCurrentTime() + seconds, true)
  }

  function seekTo(time: number) {
    if (useLocalVideo) return seekLocalTo(time)
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

  // --- Speed tier logic ---

  async function loadSpeedTiers() {
    if (!routine) return
    const result = await api.listSpeeds(routine.id)
    speedTiers = result.tiers
    tierStatus = result.status
    tierError = result.error
    // Auto-switch to local video if tiers are ready and we have 1.0x
    if (speedTiers.length > 0 && speedTiers.some(t => t.rate === 1.0)) {
      if (!useLocalVideo) switchToLocalVideo()
    }
  }

  async function triggerGeneration() {
    if (!routine) return
    await api.generateSpeeds(routine.id)
    tierStatus = 'downloading'
    // Poll for status
    startTierPolling()
  }

  function startTierPolling() {
    if (tierPollInterval) return
    tierPollInterval = setInterval(async () => {
      if (!routine) return
      const result = await api.listSpeeds(routine.id)
      speedTiers = result.tiers
      tierStatus = result.status
      tierError = result.error
      if (tierStatus === 'complete' || tierStatus === 'error' || tierStatus === 'idle') {
        clearInterval(tierPollInterval)
        tierPollInterval = undefined
        if (tierStatus === 'complete') {
          if (!useLocalVideo) switchToLocalVideo()
        }
      }
    }, 3000)
  }

  function switchToLocalVideo() {
    if (!routine || speedTiers.length === 0) return
    // Capture current time before destroying
    if (player && playerReady) {
      currentTime = player.getCurrentTime()
      player.destroy()
      player = null
      playerReady = false
    }
    useLocalVideo = true
    activeTierRate = 1.0
  }

  function switchToYouTube() {
    const savedTime = currentTime
    useLocalVideo = false
    // Recreate YouTube player after Svelte re-renders the div
    setTimeout(() => {
      createPlayer()
      // Seek to where local video was after player is ready
      const origOnReady = player?.addEventListener
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

  /**
   * Pick the best tier for a desired effective speed.
   * effective_speed = tier_rate * browser_playbackRate
   * We want browser_playbackRate to stay in a comfortable range (0.25-4.0).
   * Pick the tier that minimizes |tier_rate * playbackRate - desired|
   * while keeping playbackRate in [0.1, 4.0].
   */
  function selectTier(desiredSpeed: number): { tierRate: number; playbackRate: number } {
    let bestTier = 1.0
    let bestPlayback = desiredSpeed
    let bestError = Infinity

    for (const tier of speedTiers) {
      const playback = desiredSpeed / tier.rate
      // HTML5 playbackRate practical range
      if (playback < 0.1 || playback > 4.0) continue
      const error = Math.abs(tier.rate * playback - desiredSpeed)
      // Prefer playbackRate closer to 1.0 for quality
      const qualityPenalty = Math.abs(Math.log(playback))
      const totalError = error + qualityPenalty * 0.1
      if (totalError < bestError) {
        bestError = totalError
        bestTier = tier.rate
        bestPlayback = playback
      }
    }

    return { tierRate: bestTier, playbackRate: bestPlayback }
  }

  function applyLocalSpeed(desiredSpeed: number) {
    if (!videoEl) return
    const { tierRate, playbackRate } = selectTier(desiredSpeed)

    // Switch tier file if needed
    if (Math.abs(tierRate - activeTierRate) > 0.001 && routine) {
      const wasTime = videoEl.currentTime * (activeTierRate / tierRate)
      activeTierRate = tierRate
      videoEl.src = api.speedTierUrl(routine.id, tierRate)
      videoEl.currentTime = wasTime
      videoEl.playbackRate = playbackRate
      if (isPlaying) videoEl.play()
    } else {
      videoEl.playbackRate = playbackRate
    }
  }

  // Track local video time
  function onLocalTimeUpdate() {
    if (!videoEl) return
    // Convert local video time back to "original" time
    currentTime = videoEl.currentTime * activeTierRate
    duration = (videoEl.duration || 0) * activeTierRate
    applySegmentSpeed()
  }

  function toggleLocalPlay() {
    if (!videoEl) return
    if (videoEl.paused) {
      videoEl.play()
      isPlaying = true
    } else {
      videoEl.pause()
      isPlaying = false
    }
  }

  function seekLocalTo(time: number) {
    if (!videoEl) return
    videoEl.currentTime = time / activeTierRate
  }

  // --- Timeline scrubbing ---
  let isScrubbing = $state(false)
  let timelineEl: HTMLDivElement | null = null

  function scrubFromEvent(e: PointerEvent) {
    if (!timelineEl || !duration) return
    const rect = timelineEl.getBoundingClientRect()
    const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
    const time = pct * duration
    seekTo(time)
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
      {#if useLocalVideo && routine}
        <!-- svelte-ignore a11y_media_has_caption -->
        <video
          bind:this={videoEl}
          src={api.speedTierUrl(routine.id, activeTierRate)}
          class="w-full h-full"
          ontimeupdate={onLocalTimeUpdate}
          onplay={() => isPlaying = true}
          onpause={() => isPlaying = false}
          onloadedmetadata={() => { if (videoEl) duration = videoEl.duration * activeTierRate }}
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

    <!-- Speed tiers -->
    {#if routine}
      <div class="flex items-center justify-between pt-2 border-t border-neutral-800">
        <div class="flex items-center gap-2">
          {#if speedTiers.length > 0}
            <button
              onclick={() => useLocalVideo ? switchToYouTube() : switchToLocalVideo()}
              class="text-xs px-3 py-1.5 rounded border transition-colors {useLocalVideo
                ? 'border-blue-600 text-blue-300 bg-blue-900/30'
                : 'border-neutral-700 text-neutral-500 hover:text-neutral-300'}"
            >
              {useLocalVideo ? 'local video' : 'youtube'}
            </button>
            {#if useLocalVideo}
              <span class="text-[10px] text-neutral-500">tier: {activeTierRate}x · range: 0.05x–4x</span>
            {/if}
          {/if}
        </div>
        <div>
          {#if tierStatus === 'idle' && speedTiers.length === 0}
            <button
              onclick={triggerGeneration}
              class="text-xs px-3 py-1.5 rounded bg-neutral-800 text-neutral-400 hover:text-white hover:bg-neutral-700 transition-colors border border-neutral-700"
            >
              generate speed tiers
            </button>
          {:else if tierStatus === 'complete' || speedTiers.length > 0}
            <span class="text-[10px] text-neutral-500">{speedTiers.length} tiers ready</span>
          {:else if tierStatus === 'error'}
            <span class="text-[10px] text-red-400" title={tierError || ''}>{tierError?.slice(0, 40) || 'error'}</span>
          {:else}
            <span class="text-[10px] text-amber-400">{tierStatus}...</span>
          {/if}
        </div>
      </div>
    {/if}
  </div>
</div>
