<script lang="ts">
  let { onSubmit }: { onSubmit: (url: string) => void } = $props()
  let url = $state('')

  function handleSubmit(e: Event) {
    e.preventDefault()
    if (url.trim()) {
      onSubmit(url.trim())
      url = ''
    }
  }
</script>

<form onsubmit={handleSubmit} class="w-full flex gap-2">
  <input
    type="text"
    bind:value={url}
    placeholder="https://youtube.com/watch?v=..."
    class="flex-1 px-4 py-3 bg-neutral-900 border border-neutral-700 rounded-lg text-white placeholder-neutral-500 focus:outline-none focus:border-neutral-500"
  />
  <button
    type="submit"
    class="px-6 py-3 bg-white text-black font-medium rounded-lg hover:bg-neutral-200 transition-colors"
  >
    Play
  </button>
</form>
