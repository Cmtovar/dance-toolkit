<script lang="ts">
  import Player from './lib/Player.svelte'
  import UrlInput from './lib/UrlInput.svelte'
  import History from './lib/History.svelte'
  import Recordings from './lib/Recordings.svelte'
  import { api } from './lib/api'

  type View = { kind: 'home' } | { kind: 'player'; videoId: string; url: string } | { kind: 'history' } | { kind: 'recordings' }

  let view = $state<View>({ kind: 'home' })

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

  function handleUrl(url: string) {
    const id = extractVideoId(url)
    if (id) view = { kind: 'player', videoId: id, url }
  }

  async function openRoutineById(routineId: number) {
    const routine = await api.getRoutine(routineId)
    const alt = routine.alternates?.[0]
    if (!alt) return
    const id = extractVideoId(alt.youtube_url)
    if (id) view = { kind: 'player', videoId: id, url: alt.youtube_url }
  }
</script>

<main class="min-h-screen flex flex-col">
  <header class="px-4 py-3 border-b border-neutral-800 flex items-center justify-between">
    <button onclick={() => view = { kind: 'home' }} class="text-lg font-medium hover:text-neutral-300 transition-colors">
      Dance Toolkit
    </button>
    <div class="flex items-center gap-3">
      {#if view.kind !== 'recordings'}
        <button
          onclick={() => view = { kind: 'recordings' }}
          class="text-sm text-neutral-400 hover:text-white transition-colors"
        >
          recordings
        </button>
      {/if}
      {#if view.kind !== 'history'}
        <button
          onclick={() => view = { kind: 'history' }}
          class="text-sm text-neutral-400 hover:text-white transition-colors"
        >
          history
        </button>
      {/if}
    </div>
  </header>

  <div class="flex-1 flex flex-col items-center p-4 gap-6">
    {#if view.kind === 'home'}
      <div class="w-full max-w-xl flex flex-col items-center gap-4 mt-16">
        <p class="text-neutral-400 text-center">Paste a YouTube URL to start</p>
        <UrlInput onSubmit={handleUrl} />
      </div>
    {:else if view.kind === 'player'}
      <Player
        videoId={view.videoId}
        sourceUrl={view.url}
        onBack={() => view = { kind: 'home' }}
      />
    {:else if view.kind === 'history'}
      <History
        onBack={() => view = { kind: 'home' }}
        onOpen={(videoId, url) => view = { kind: 'player', videoId, url }}
      />
    {:else if view.kind === 'recordings'}
      <Recordings
        onBack={() => view = { kind: 'home' }}
        onOpenRoutine={openRoutineById}
      />
    {/if}
  </div>
</main>
