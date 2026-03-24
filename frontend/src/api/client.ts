export interface Project {
  id: string
  name: string
}

export interface WordEntry {
  word: string
  count: number
}

export interface GraphNode {
  id: string
  word: string
  count: number
}

export interface GraphEdge {
  source: string
  target: string
  weight: number
}

export interface WordGraph {
  nodes: GraphNode[]
  edges: GraphEdge[]
}

export interface StreamUpdate {
  wordcloud: WordEntry[]
  wordgraph: WordGraph
}

const BASE = '/api'

export async function fetchProjects(): Promise<Project[]> {
  const r = await fetch(`${BASE}/projects`)
  if (!r.ok) throw new Error(`Failed to fetch projects: ${r.statusText}`)
  return r.json()
}

export async function fetchWordCloud(projectId: string, filter: string): Promise<WordEntry[]> {
  const r = await fetch(`${BASE}/wordcloud?project_id=${projectId}&filter=${filter}`)
  if (!r.ok) throw new Error(`Failed to fetch word cloud: ${r.statusText}`)
  return r.json()
}

export async function fetchWordGraph(projectId: string, filter: string): Promise<WordGraph> {
  const r = await fetch(`${BASE}/wordgraph?project_id=${projectId}&filter=${filter}`)
  if (!r.ok) throw new Error(`Failed to fetch word graph: ${r.statusText}`)
  return r.json()
}

export async function fetchSummary(projectId: string, filter: string): Promise<string> {
  const r = await fetch(`${BASE}/summary?project_id=${projectId}&filter=${filter}`)
  if (!r.ok) {
    const body = await r.json().catch(() => ({}))
    throw new Error(body.detail ?? `Failed to fetch summary: ${r.statusText}`)
  }
  const data = await r.json()
  return data.summary
}

export function openStream(
  projectId: string,
  filter: string,
  onUpdate: (data: StreamUpdate) => void,
  onError: (err: string) => void,
): EventSource {
  const es = new EventSource(`${BASE}/stream?project_id=${projectId}&filter=${filter}`)
  es.addEventListener('update', (e: MessageEvent) => {
    try {
      onUpdate(JSON.parse(e.data))
    } catch {
      onError('Failed to parse stream update')
    }
  })
  es.addEventListener('error', (e: MessageEvent) => {
    try {
      const d = JSON.parse(e.data)
      onError(d.error ?? 'Stream error')
    } catch {
      // connection errors — ignore, browser will reconnect
    }
  })
  return es
}
