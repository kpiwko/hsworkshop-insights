<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import cloud from 'd3-cloud'
import type { Word } from 'd3-cloud'
import type { WordEntry } from '../api/client'

const props = defineProps<{
  words: WordEntry[]
}>()

const container = ref<HTMLDivElement>()

interface CloudWord extends Word {
  count: number
}

// Deterministic rotation based on word text — stable across re-renders
function wordRotation(text: string): number {
  return text.charCodeAt(0) % 7 === 0 ? 90 : 0
}

function getSize(): { w: number; h: number } {
  if (!container.value) return { w: 600, h: 460 }
  // offsetWidth/Height are reliable even when getBoundingClientRect returns 0
  const w = container.value.offsetWidth || container.value.parentElement?.offsetWidth || 600
  const h = container.value.offsetHeight || container.value.parentElement?.offsetHeight || 460
  return { w, h }
}

function render(words: WordEntry[]) {
  if (!container.value || words.length === 0) return

  const { w, h } = getSize()

  const maxCount = Math.max(...words.map(d => d.count), 1)
  const fontSize = d3.scaleSqrt().domain([1, maxCount]).range([13, Math.min(72, h / 6)])
  const color = d3.scaleSequential(d3.interpolateCool).domain([0, words.length])

  container.value.innerHTML = ''

  const cloudWords: CloudWord[] = words.map(d => ({
    text: d.word,
    count: d.count,
    size: fontSize(d.count),
  }))

  cloud<CloudWord>()
    .size([w, h])
    .words(cloudWords)
    .padding(5)
    .rotate(d => wordRotation(d.text ?? ''))
    .fontSize(d => d.size ?? 13)
    .font('Inter, sans-serif')
    .on('end', (drawn: CloudWord[]) => {
      const svg = d3
        .select(container.value!)
        .append('svg')
        .attr('viewBox', `0 0 ${w} ${h}`)
        .style('width', '100%')
        .style('height', '100%')

      svg
        .append('g')
        .attr('transform', `translate(${w / 2},${h / 2})`)
        .selectAll('text')
        .data(drawn)
        .join('text')
        .style('font-size', (d: CloudWord) => `${d.size}px`)
        .style('font-family', 'Inter, sans-serif')
        .style('font-weight', '600')
        .style('fill', (_: CloudWord, i: number) => color(i))
        .attr('text-anchor', 'middle')
        .attr('transform', (d: CloudWord) =>
          `translate(${d.x ?? 0},${d.y ?? 0}) rotate(${d.rotate ?? 0})`,
        )
        .text((d: CloudWord) => d.text ?? '')
        .append('title')
        .text((d: CloudWord) => `${d.text}: ${d.count}`)
    })
    .start()
}

let ro: ResizeObserver | undefined
onMounted(() => {
  // Defer first render to ensure layout is complete
  requestAnimationFrame(() => render(props.words))
  if (container.value) {
    ro = new ResizeObserver(() => render(props.words))
    ro.observe(container.value)
  }
})
onUnmounted(() => ro?.disconnect())
watch(() => props.words, words => render(words))
</script>

<template>
  <div ref="container" class="w-full h-full" />
</template>
