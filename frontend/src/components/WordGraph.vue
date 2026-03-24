<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import * as d3 from 'd3'
import type { WordGraph } from '../api/client'

const props = defineProps<{
  graph: WordGraph
}>()

const container = ref<SVGSVGElement>()

type SimNode = d3.SimulationNodeDatum & { id: string; word: string; count: number }
type SimLink = d3.SimulationLinkDatum<SimNode> & { weight: number }

function render(graph: WordGraph) {
  if (!container.value || graph.nodes.length === 0) return

  const svg = d3.select(container.value)
  svg.selectAll('*').remove()

  const w = container.value.clientWidth || container.value.parentElement?.clientWidth || 600
  const h = container.value.clientHeight || container.value.parentElement?.clientHeight || 400

  const maxCount = Math.max(...graph.nodes.map(n => n.count), 1)
  const maxWeight = Math.max(...graph.edges.map(e => e.weight), 1)

  const nodeRadius = d3.scaleLinear().domain([1, maxCount]).range([6, 28])
  const edgeWidth = d3.scaleLinear().domain([1, maxWeight]).range([0.5, 4])
  const color = d3.scaleSequential(d3.interpolateTurbo).domain([0, maxCount])

  const nodes: SimNode[] = graph.nodes.map(n => ({ ...n }))
  const nodeById = new Map(nodes.map(n => [n.id, n]))

  const links: SimLink[] = graph.edges
    .filter(e => nodeById.has(e.source) && nodeById.has(e.target))
    .map(e => ({ source: nodeById.get(e.source)!, target: nodeById.get(e.target)!, weight: e.weight }))

  const sim = d3
    .forceSimulation<SimNode>(nodes)
    .force('link', d3.forceLink<SimNode, SimLink>(links).id(d => d.id).distance(80))
    .force('charge', d3.forceManyBody().strength(-120))
    .force('center', d3.forceCenter(w / 2, h / 2))
    .force('collision', d3.forceCollide<SimNode>(d => nodeRadius(d.count) + 4))

  const g = svg.append('g')

  // Zoom
  svg.call(
    d3.zoom<SVGSVGElement, unknown>().on('zoom', e => g.attr('transform', e.transform)),
  )

  const link = g
    .append('g')
    .selectAll('line')
    .data(links)
    .join('line')
    .attr('stroke', '#94a3b8')
    .attr('stroke-opacity', 0.6)
    .attr('stroke-width', d => edgeWidth(d.weight))

  const node = g
    .append('g')
    .selectAll<SVGGElement, SimNode>('g')
    .data(nodes)
    .join('g')
    .call(
      d3
        .drag<SVGGElement, SimNode>()
        .on('start', (event, d) => {
          if (!event.active) sim.alphaTarget(0.3).restart()
          d.fx = d.x; d.fy = d.y
        })
        .on('drag', (event, d) => { d.fx = event.x; d.fy = event.y })
        .on('end', (event, d) => {
          if (!event.active) sim.alphaTarget(0)
          d.fx = null; d.fy = null
        }),
    )

  node
    .append('circle')
    .attr('r', d => nodeRadius(d.count))
    .attr('fill', d => color(d.count))
    .attr('fill-opacity', 0.85)
    .attr('stroke', '#fff')
    .attr('stroke-width', 1.5)

  node
    .append('text')
    .text(d => d.word)
    .attr('text-anchor', 'middle')
    .attr('dy', '0.35em')
    .style('font-size', d => `${Math.max(9, nodeRadius(d.count) * 0.7)}px`)
    .style('font-family', 'Inter, sans-serif')
    .style('font-weight', '500')
    .style('fill', '#1e293b')
    .style('pointer-events', 'none')

  node.append('title').text(d => `${d.word} (${d.count})`)

  sim.on('tick', () => {
    link
      .attr('x1', d => (d.source as SimNode).x!)
      .attr('y1', d => (d.source as SimNode).y!)
      .attr('x2', d => (d.target as SimNode).x!)
      .attr('y2', d => (d.target as SimNode).y!)

    node.attr('transform', d => `translate(${d.x},${d.y})`)
  })
}

onMounted(() => requestAnimationFrame(() => render(props.graph)))
watch(() => props.graph, g => render(g))

let ro: ResizeObserver | undefined
onMounted(() => {
  if (container.value) {
    ro = new ResizeObserver(() => render(props.graph))
    ro.observe(container.value)
  }
})
onUnmounted(() => ro?.disconnect())
</script>

<template>
  <svg ref="container" class="w-full h-full" />
</template>
