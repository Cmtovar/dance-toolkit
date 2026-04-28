<script lang="ts">
  import { onMount } from 'svelte'
  import { api, type Routine } from './api'

  let { onBack, onOpen }: { onBack: () => void; onOpen: (videoId: string, url: string) => void } = $props()

  let routines = $state<Routine[]>([])
  let loading = $state(true)

  onMount(load)

  async function load() {
    loading = true
    const list = await api.listRoutines()
    // Load full details to get alternates
    routines = await Promise.all(list.map((r: Routine) => api.getRoutine(r.id)))
    loading = false
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

  async function deleteRoutine(id: number) {
    if (!confirm('Delete this routine and all its markers?')) return
    await api.deleteRoutine(id)
    await load()
  }
</script>

<div class="w-full max-w-2xl mx-auto flex flex-col gap-4">
  <div class="flex items-center gap-3">
    <button onclick={onBack} class="text-neutral-400 hover:text-white transition-colors text-sm">← back</button>
    <h2 class="text-lg font-medium">History</h2>
  </div>

  {#if loading}
    <p class="text-neutral-500 text-center py-8">Loading...</p>
  {:else if routines.length === 0}
    <p class="text-neutral-500 text-center py-8">No routines yet. Start by pasting a video and dropping markers.</p>
  {:else}
    <div class="flex flex-col gap-2">
      {#each routines as routine}
        {@const alt = routine.alternates?.[0]}
        {@const vid = alt ? extractVideoId(alt.youtube_url) : null}
        <div class="flex items-center gap-3 bg-neutral-900 rounded-lg p-3 group">
          {#if vid}
            <img
              src="https://img.youtube.com/vi/{vid}/default.jpg"
              alt=""
              class="w-16 h-12 rounded object-cover flex-shrink-0"
            />
          {/if}
          <div
            class="flex-1 cursor-pointer"
            role="button"
            tabindex="0"
            onclick={() => { if (vid && alt) onOpen(vid, alt.youtube_url) }}
            onkeydown={(e: KeyboardEvent) => { if (e.key === 'Enter' && vid && alt) onOpen(vid, alt.youtube_url) }}
          >
            <div class="text-sm text-white">{routine.name}</div>
            <div class="text-xs text-neutral-500">
              {routine.move_count ?? 0} segments
              {#if routine.timing_floor != null}
                · floor: {routine.timing_floor.toFixed(2)}x
              {/if}
            </div>
          </div>
          <button
            onclick={() => deleteRoutine(routine.id)}
            class="text-neutral-600 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
          >
            ✕
          </button>
        </div>
      {/each}
    </div>
  {/if}
</div>
