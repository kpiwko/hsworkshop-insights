<script setup lang="ts">
import { onMounted, onUnmounted, ref, watch } from 'vue'
import WordCloud from './components/WordCloud.vue'
import WordGraph from './components/WordGraph.vue'
import SummaryPanel from './components/SummaryPanel.vue'
import {
  fetchProjects,
  fetchWordCloud,
  fetchWordGraph,
  openStream,
} from './api/client'
import type { Project, WordEntry, WordGraph as WordGraphData } from './api/client'

type Filter = 'valid' | 'all' | 'blocked'

const STORAGE_KEY = 'hsworkshop-insights-project'

const projects = ref<Project[]>([])
const selectedProjectId = ref(localStorage.getItem(STORAGE_KEY) ?? '')
const filter = ref<Filter>('valid')
const activeTab = ref<'cloud' | 'graph' | 'summary'>('cloud')

const words = ref<WordEntry[]>([])
const graph = ref<WordGraphData>({ nodes: [], edges: [] })
const loading = ref(false)
const error = ref('')
const lastUpdated = ref<Date | null>(null)

let es: EventSource | null = null

async function loadData() {
  if (!selectedProjectId.value) return
  loading.value = true
  error.value = ''
  try {
    const [w, g] = await Promise.all([
      fetchWordCloud(selectedProjectId.value, filter.value),
      fetchWordGraph(selectedProjectId.value, filter.value),
    ])
    words.value = w
    graph.value = g
    lastUpdated.value = new Date()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    loading.value = false
  }
}

function connectStream() {
  es?.close()
  if (!selectedProjectId.value) return
  es = openStream(
    selectedProjectId.value,
    filter.value,
    update => {
      words.value = update.wordcloud
      graph.value = update.wordgraph
      lastUpdated.value = new Date()
    },
    err => { error.value = err },
  )
}

onMounted(async () => {
  try {
    projects.value = await fetchProjects()
    // Restore saved project or fall back to first
    if (!selectedProjectId.value || !projects.value.find(p => p.id === selectedProjectId.value)) {
      selectedProjectId.value = projects.value[0]?.id ?? ''
    }
    await loadData()
    connectStream()
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  }
})

watch(selectedProjectId, id => {
  localStorage.setItem(STORAGE_KEY, id)
  loadData()
  connectStream()
})

watch(filter, () => {
  loadData()
  connectStream()
})

onUnmounted(() => es?.close())

function formatTime(d: Date | null) {
  if (!d) return '—'
  return d.toLocaleTimeString()
}

const filterOptions: { value: Filter; label: string }[] = [
  { value: 'valid', label: '✅ Valid only' },
  { value: 'all',   label: '🔀 All' },
  { value: 'blocked', label: '⚠️ Blocked only' },
]
</script>

<template>
  <!--
    h-screen gives an explicit 100vh height so every child can use h-full / height:100%.
    min-h-0 on flex children prevents them from overflowing their parent.
  -->
  <div class="h-screen bg-gradient-to-br from-slate-50 to-blue-50 text-slate-800 flex flex-col overflow-hidden">
    <!-- Header -->
    <header class="shrink-0 border-b border-slate-200 bg-white/80 backdrop-blur px-6 py-4 flex items-center gap-6 flex-wrap shadow-sm">
      <h1 class="text-xl font-bold tracking-tight text-slate-800 flex items-center gap-2">
        <span class="text-2xl">📊</span> HSWorkshop Insights
      </h1>

      <!-- Project selector -->
      <div class="flex items-center gap-2">
        <label class="text-slate-500 text-sm font-medium">Project</label>
        <select
          v-model="selectedProjectId"
          class="bg-white border border-slate-300 rounded-lg px-3 py-1.5 text-sm text-slate-800
                 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
        </select>
      </div>

      <!-- Filter toggle -->
      <div class="flex items-center gap-1 bg-slate-100 rounded-lg p-1">
        <button
          v-for="opt in filterOptions"
          :key="opt.value"
          class="px-3 py-1 rounded-md text-xs font-medium transition-colors"
          :class="filter === opt.value
            ? 'bg-white text-slate-800 shadow-sm'
            : 'text-slate-500 hover:text-slate-700'"
          @click="filter = opt.value"
        >
          {{ opt.label }}
        </button>
      </div>

      <!-- Refresh -->
      <button
        class="ml-auto flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-100 text-slate-700
               hover:bg-slate-200 text-sm font-medium transition-colors disabled:opacity-40"
        :disabled="loading"
        @click="loadData"
      >
        <svg class="w-4 h-4" :class="{ 'animate-spin': loading }" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M4 4v5h5M20 20v-5h-5M4 9a9 9 0 0114.13-3.87M20 15a9 9 0 01-14.13 3.87" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        {{ loading ? 'Loading…' : 'Refresh' }}
      </button>

      <span class="text-slate-400 text-xs">Live · {{ formatTime(lastUpdated) }}</span>
    </header>

    <!-- Error banner -->
    <div v-if="error" class="bg-red-50 border-b border-red-200 px-6 py-2 text-red-600 text-sm">
      {{ error }}
    </div>

    <!-- Tabs -->
    <nav class="shrink-0 flex gap-1 px-6 pt-4">
      <button
        v-for="tab in [['cloud', '☁️ Word Cloud'], ['graph', '🕸️ Word Graph'], ['summary', '✨ AI Summary']] as const"
        :key="tab[0]"
        class="px-4 py-2 rounded-t-lg text-sm font-medium transition-colors"
        :class="activeTab === tab[0]
          ? 'bg-white text-indigo-600 border border-b-white border-slate-200 shadow-sm'
          : 'text-slate-500 hover:text-slate-700 hover:bg-white/60'"
        @click="activeTab = tab[0]"
      >
        {{ tab[1] }}
      </button>
    </nav>

    <!-- Content — flex-1 min-h-0 lets it shrink into h-screen -->
    <main class="flex-1 min-h-0 px-6 pb-6 flex flex-col gap-2">
      <div class="flex-1 min-h-0 bg-white rounded-b-xl rounded-tr-xl p-4 flex flex-col border border-slate-200 shadow-sm">

        <!-- Empty state -->
        <div v-if="!selectedProjectId || (words.length === 0 && activeTab !== 'summary')"
             class="flex-1 flex items-center justify-center text-slate-400 text-sm italic">
          <span v-if="loading">Loading…</span>
          <span v-else>No conversation data yet for this project.</span>
        </div>

        <template v-else>
          <!-- flex-1 min-h-0: fills parent, can shrink; h-full on child then resolves correctly -->
          <div v-show="activeTab === 'cloud'" class="flex-1 min-h-0">
            <WordCloud :words="words" />
          </div>

          <div v-show="activeTab === 'graph'" class="flex-1 min-h-0">
            <WordGraph :graph="graph" />
          </div>

          <div v-show="activeTab === 'summary'" class="flex-1 min-h-0 overflow-y-auto">
            <SummaryPanel
              :project-id="selectedProjectId"
              :filter="filter"
            />
          </div>
        </template>
      </div>

      <!-- Stats footer -->
      <div class="shrink-0 flex gap-6 text-xs text-slate-400">
        <span>{{ words.length }} unique words</span>
        <span>{{ graph.nodes.length }} graph nodes · {{ graph.edges.length }} edges</span>
      </div>
    </main>
  </div>
</template>
