<script lang="ts">
  import { api, type Attempt } from './api'
  import { saveVideo } from './videoStore'

  let { routineId, moveId, onRecorded }: {
    routineId: number
    moveId: number
    onRecorded: (attempt: Attempt) => void
  } = $props()

  type RecorderState = 'idle' | 'requesting' | 'ready' | 'recording' | 'saving'

  let state = $state<RecorderState>('idle')
  let stream: MediaStream | null = null
  let recorder: MediaRecorder | null = null
  let chunks: Blob[] = []
  let previewEl = $state<HTMLVideoElement | null>(null)
  let error = $state<string | null>(null)
  let elapsed = $state(0)
  let timerInterval: number | undefined

  async function startCamera() {
    state = 'requesting'
    error = null
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: 'user', width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: true,
      })
      state = 'ready'
      if (previewEl) previewEl.srcObject = stream
    } catch (e: any) {
      error = e.message || 'Camera access denied'
      state = 'idle'
    }
  }

  function startRecording() {
    if (!stream) return
    chunks = []
    const mimeType = MediaRecorder.isTypeSupported('video/webm;codecs=vp9,opus')
      ? 'video/webm;codecs=vp9,opus'
      : MediaRecorder.isTypeSupported('video/webm')
        ? 'video/webm'
        : 'video/mp4'
    recorder = new MediaRecorder(stream, { mimeType })
    recorder.ondataavailable = (e) => { if (e.data.size > 0) chunks.push(e.data) }
    recorder.onstop = handleRecordingDone
    recorder.start(1000)
    state = 'recording'
    elapsed = 0
    timerInterval = setInterval(() => elapsed++, 1000)
  }

  function stopRecording() {
    if (recorder && recorder.state === 'recording') recorder.stop()
    if (timerInterval) { clearInterval(timerInterval); timerInterval = undefined }
  }

  async function handleRecordingDone() {
    const mimeType = recorder?.mimeType || 'video/webm'
    const blob = new Blob(chunks, { type: mimeType })
    stopCamera()
    state = 'saving'

    try {
      const attempt = await api.createAttempt(routineId, moveId, { mime_type: mimeType })
      await saveVideo(attempt.id, blob)
      onRecorded(attempt)
      state = 'idle'
    } catch (e: any) {
      error = e.message || 'Failed to save'
      state = 'idle'
    }
  }

  function stopCamera() {
    if (stream) { stream.getTracks().forEach(t => t.stop()); stream = null }
  }

  function cancel() {
    stopRecording()
    stopCamera()
    state = 'idle'
    error = null
  }

  function formatElapsed(s: number): string {
    const m = Math.floor(s / 60)
    const sec = s % 60
    return `${m}:${sec.toString().padStart(2, '0')}`
  }

  $effect(() => {
    if (previewEl && stream) previewEl.srcObject = stream
  })
</script>

{#if state === 'idle'}
  <button
    onclick={startCamera}
    class="text-xs px-3 py-1.5 rounded bg-red-900/30 text-red-300 hover:bg-red-900/50 transition-colors border border-red-800/50"
  >
    record
  </button>
{:else if state === 'requesting'}
  <span class="text-xs text-neutral-500">requesting camera...</span>
{:else if state === 'ready' || state === 'recording'}
  <div class="flex flex-col gap-2 w-full">
    <div class="relative w-full aspect-video bg-black rounded-lg overflow-hidden">
      <!-- svelte-ignore a11y_media_has_caption -->
      <video
        bind:this={previewEl}
        autoplay
        muted
        playsinline
        class="w-full h-full object-cover"
        style:transform="scaleX(-1)"
      ></video>
      {#if state === 'recording'}
        <div class="absolute top-2 right-2 flex items-center gap-1.5 bg-black/60 rounded px-2 py-1">
          <div class="w-2 h-2 rounded-full bg-red-500 animate-pulse"></div>
          <span class="text-xs text-white font-mono">{formatElapsed(elapsed)}</span>
        </div>
      {/if}
    </div>
    <div class="flex items-center justify-center gap-3">
      {#if state === 'ready'}
        <button
          onclick={startRecording}
          class="w-10 h-10 rounded-full bg-red-500 hover:bg-red-400 transition-colors flex items-center justify-center"
          title="Start recording"
        >
          <div class="w-4 h-4 rounded-full bg-white"></div>
        </button>
      {:else}
        <button
          onclick={stopRecording}
          class="w-10 h-10 rounded-full bg-red-500 hover:bg-red-400 transition-colors flex items-center justify-center"
          title="Stop recording"
        >
          <div class="w-4 h-4 rounded-sm bg-white"></div>
        </button>
      {/if}
      <button
        onclick={cancel}
        class="text-xs text-neutral-500 hover:text-white transition-colors"
      >
        cancel
      </button>
    </div>
  </div>
{:else if state === 'saving'}
  <div class="flex items-center gap-2">
    <div class="w-3 h-3 border-2 border-neutral-400 border-t-transparent rounded-full animate-spin"></div>
    <span class="text-xs text-neutral-400">saving...</span>
  </div>
{/if}

{#if error}
  <span class="text-xs text-red-400">{error}</span>
{/if}
