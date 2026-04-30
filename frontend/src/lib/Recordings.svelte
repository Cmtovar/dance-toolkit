<script lang="ts">
  import { onMount } from 'svelte'
  import { api, type AttemptWithContext } from './api'
  import { getVideo, deleteVideo } from './videoStore'

  let { onBack, onOpenRoutine }: {
    onBack: () => void
    onOpenRoutine: (routineId: number) => void
  } = $props()

  let attempts = $state<AttemptWithContext[]>([])
  let loading = $state(true)
  let playingId = $state<number | null>(null)
  let blobUrls = $state<Record<number, string>>({})
  let editingId = $state<number | null>(null)
  let editingNotes = $state('')
  let uploadingId = $state<number | null>(null)

  onMount(() => {
    loadAttempts()
  })

  async function loadAttempts() {
    loading = true
    attempts = await api.allAttempts()
    loading = false
  }

  async function play(attempt: AttemptWithContext) {
    if (playingId === attempt.id) {
      playingId = null
      return
    }
    if (!blobUrls[attempt.id]) {
      const blob = await getVideo(attempt.id)
      if (blob) blobUrls[attempt.id] = URL.createObjectURL(blob)
    }
    playingId = attempt.id
  }

  function startEditing(attempt: AttemptWithContext) {
    editingId = attempt.id
    editingNotes = attempt.notes || ''
  }

  async function saveEditing(attempt: AttemptWithContext) {
    await api.updateAttempt(attempt.id, { notes: editingNotes })
    editingId = null
    await loadAttempts()
  }

  async function deleteAttempt(attempt: AttemptWithContext) {
    await api.deleteAttempt(attempt.routine_id, attempt.move_id, attempt.id)
    await deleteVideo(attempt.id)
    if (blobUrls[attempt.id]) {
      URL.revokeObjectURL(blobUrls[attempt.id])
      delete blobUrls[attempt.id]
    }
    if (playingId === attempt.id) playingId = null
    await loadAttempts()
  }

  async function uploadToYouTube(attempt: AttemptWithContext) {
    uploadingId = attempt.id
    try {
      const blob = await getVideo(attempt.id)
      if (!blob) throw new Error('Video not found locally')
      const title = attempt.notes || `attempt ${attempt.id}`
      const videoId = await api.uploadToYouTube(blob, title)
      await api.updateAttempt(attempt.id, {
        youtube_url: `https://www.youtube.com/watch?v=${videoId}`,
        upload_status: 'on_youtube',
      })
      await loadAttempts()
    } catch (e: any) {
      alert(`Upload failed: ${e.message || 'unknown error'}`)
    } finally {
      uploadingId = null
    }
  }

  function formatDate(recorded: string): string {
    const d = new Date(recorded + 'Z')
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: 'numeric', minute: '2-digit' })
  }
</script>

<div class="w-full max-w-2xl flex flex-col gap-4">
  <button
    onclick={onBack}
    class="self-start text-neutral-400 hover:text-white transition-colors text-sm"
  >
    ← back
  </button>

  <h2 class="text-lg text-neutral-300">Recordings</h2>

  {#if loading}
    <span class="text-sm text-neutral-500">loading...</span>
  {:else if attempts.length === 0}
    <p class="text-sm text-neutral-500">No recordings yet. Record an attempt from any segment.</p>
  {:else}
    <div class="flex flex-col gap-2">
      {#each attempts as attempt}
        <div class="bg-neutral-900 rounded-lg p-3 flex flex-col gap-2 group">
          <div class="flex items-center gap-3">
            <div
              onclick={() => play(attempt)}
              class="flex-1 cursor-pointer"
              role="button"
              tabindex="0"
              onkeydown={(e) => { if (e.key === 'Enter') play(attempt) }}
            >
              <div class="flex items-baseline gap-2">
                {#if attempt.notes}
                  <span class="text-sm text-neutral-200">{attempt.notes}</span>
                {/if}
                <span class="text-xs text-neutral-500">{formatDate(attempt.recorded)}</span>
              </div>
              <div class="text-[11px] text-neutral-600 mt-0.5">
                <button
                  onclick={(e) => { e.stopPropagation(); onOpenRoutine(attempt.routine_id) }}
                  class="hover:text-neutral-400 transition-colors"
                >
                  {attempt.routine_name}
                </button>
                · {attempt.start_time > 0 ? `${Math.floor(attempt.start_time / 60)}:${String(Math.floor(attempt.start_time % 60)).padStart(2, '0')}` : '0:00'}
              </div>
            </div>

            <div class="flex items-center gap-2">
              {#if attempt.upload_status === 'on_youtube'}
                <span class="text-[10px] text-green-600">yt</span>
              {:else if uploadingId === attempt.id}
                <div class="w-3 h-3 border border-neutral-400 border-t-transparent rounded-full animate-spin"></div>
              {:else}
                <button
                  onclick={() => uploadToYouTube(attempt)}
                  class="text-[10px] text-neutral-600 hover:text-neutral-300 opacity-0 group-hover:opacity-100 transition-opacity"
                  title="Upload to YouTube"
                >
                  yt↑
                </button>
              {/if}
              <button
                onclick={() => startEditing(attempt)}
                class="text-[10px] text-neutral-600 hover:text-neutral-300 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Name this recording"
              >
                ✎
              </button>
              <button
                onclick={() => deleteAttempt(attempt)}
                class="text-xs text-neutral-600 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
              >
                x
              </button>
            </div>
          </div>

          {#if editingId === attempt.id}
            <form
              onsubmit={(e) => { e.preventDefault(); saveEditing(attempt) }}
              class="flex items-center gap-1"
            >
              <input
                type="text"
                bind:value={editingNotes}
                placeholder="name this recording..."
                class="flex-1 bg-neutral-800 text-xs text-neutral-200 rounded px-2 py-1 border border-neutral-700 focus:border-neutral-500 outline-none"
                autofocus
              />
              <button type="submit" class="text-xs text-neutral-400 hover:text-white">save</button>
              <button type="button" onclick={() => editingId = null} class="text-xs text-neutral-600 hover:text-neutral-400">cancel</button>
            </form>
          {/if}

          {#if playingId === attempt.id}
            <div class="w-full aspect-video bg-black rounded overflow-hidden">
              {#if blobUrls[attempt.id]}
                <!-- svelte-ignore a11y_media_has_caption -->
                <video
                  src={blobUrls[attempt.id]}
                  class="w-full h-full"
                  controls
                  playsinline
                  autoplay
                ></video>
              {:else if attempt.youtube_url}
                <iframe
                  src="https://www.youtube.com/embed/{attempt.youtube_url.split('v=')[1]}?autoplay=1&playsinline=1"
                  class="w-full h-full"
                  allow="autoplay"
                  title="Attempt recording"
                ></iframe>
              {:else}
                <div class="w-full h-full flex items-center justify-center text-neutral-500 text-sm">
                  Video not available on this device
                </div>
              {/if}
            </div>
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>
