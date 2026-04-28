<script lang="ts">
  let { speed = $bindable(1.0) }: { speed: number } = $props()

  const presets = [0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0]

  function handleSlider(e: Event) {
    const target = e.target as HTMLInputElement
    speed = parseFloat(target.value)
  }

  function nudge(amount: number) {
    speed = Math.round(Math.max(0.25, Math.min(2.0, speed + amount)) * 100) / 100
  }
</script>

<div class="flex flex-col gap-2">
  <div class="flex items-center justify-between">
    <span class="text-sm text-neutral-400">Speed</span>
    <div class="flex items-center gap-2">
      <button
        onclick={() => nudge(-0.05)}
        class="text-neutral-400 hover:text-white transition-colors w-7 h-7 flex items-center justify-center rounded bg-neutral-800 text-sm"
      >
        −
      </button>
      <span class="text-white font-mono text-sm w-14 text-center">{speed.toFixed(2)}x</span>
      <button
        onclick={() => nudge(0.05)}
        class="text-neutral-400 hover:text-white transition-colors w-7 h-7 flex items-center justify-center rounded bg-neutral-800 text-sm"
      >
        +
      </button>
    </div>
  </div>

  <!-- Slider -->
  <input
    type="range"
    min="0.25"
    max="2.0"
    step="0.01"
    value={speed}
    oninput={handleSlider}
    class="w-full h-1.5 bg-neutral-700 rounded-full appearance-none cursor-pointer
           [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:h-4
           [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:cursor-pointer"
  />

  <!-- Presets -->
  <div class="flex gap-1.5 flex-wrap">
    {#each presets as preset}
      <button
        onclick={() => speed = preset}
        class="text-xs px-2.5 py-1 rounded transition-colors {Math.abs(speed - preset) < 0.01
          ? 'bg-white text-black'
          : 'bg-neutral-800 text-neutral-400 hover:text-white'}"
      >
        {preset}x
      </button>
    {/each}
  </div>
</div>
