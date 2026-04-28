<script lang="ts">
  import { onMount } from 'svelte'
  import SpeedControl from './SpeedControl.svelte'

  let { videoId, onBack }: { videoId: string; onBack: () => void } = $props()

  let player: YT.Player | null = null
  let playerReady = $state(false)
  let mirrored = $state(true)
  let speed = $state(1.0)
  let isPlaying = $state(false)
  const playerId = 'yt-player-' + Math.random().toString(36).slice(2)

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
    return () => player?.destroy()
  })

  $effect(() => {
    if (playerReady && player) {
      player.setPlaybackRate(speed)
    }
  })

  function togglePlay() {
    if (!player || !playerReady) return
    if (isPlaying) {
      player.pauseVideo()
    } else {
      player.playVideo()
    }
  }

  function skip(seconds: number) {
    if (!player || !playerReady) return
    const current = player.getCurrentTime()
    player.seekTo(current + seconds, true)
  }
</script>

<div class="w-full max-w-4xl flex flex-col gap-4">
  <!-- Back button -->
  <button
    onclick={onBack}
    class="self-start text-neutral-400 hover:text-white transition-colors text-sm flex items-center gap-1"
  >
    ← back
  </button>

  <!-- Video container -->
  <div
    class="relative w-full bg-black rounded-lg overflow-hidden"
    style:transform={mirrored ? 'scaleX(-1)' : 'none'}
  >
    <div class="aspect-video">
      <div id={playerId} class="w-full h-full"></div>
    </div>
  </div>

  <!-- Controls -->
  <div class="flex flex-col gap-3 bg-neutral-900 rounded-lg p-4">
    <!-- Playback controls -->
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
    </div>

    <!-- Speed control -->
    <SpeedControl bind:speed />

    <!-- Mirror toggle (off to the side, not prominent) -->
    <div class="flex justify-end">
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
