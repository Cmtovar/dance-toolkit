<script lang="ts">
  import Player from './lib/Player.svelte'
  import UrlInput from './lib/UrlInput.svelte'

  let videoId = $state('')

  function handleUrl(url: string) {
    const id = extractVideoId(url)
    if (id) videoId = id
  }

  function extractVideoId(url: string): string | null {
    try {
      const u = new URL(url)
      if (u.hostname === 'youtu.be') return u.pathname.slice(1)
      if (u.hostname.includes('youtube.com')) return u.searchParams.get('v')
    } catch {
      // might be just an ID
      if (/^[a-zA-Z0-9_-]{11}$/.test(url)) return url
    }
    return null
  }
</script>

<main class="min-h-screen flex flex-col">
  <header class="px-4 py-3 border-b border-neutral-800">
    <h1 class="text-lg font-medium">Dance Toolkit</h1>
  </header>

  <div class="flex-1 flex flex-col items-center justify-center p-4 gap-6">
    {#if !videoId}
      <div class="w-full max-w-xl flex flex-col items-center gap-4">
        <p class="text-neutral-400 text-center">Paste a YouTube URL to start practicing</p>
        <UrlInput onSubmit={handleUrl} />
      </div>
    {:else}
      <Player {videoId} onBack={() => videoId = ''} />
    {/if}
  </div>
</main>
