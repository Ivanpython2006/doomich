import type { CampusGraph } from '../api/types'

export interface GraphStats {
  buildings: number
  floors: number
  nodes: number
  edges: number
  rooms: number
}

const nodeKinds = new Set(['corridor', 'room', 'stairs', 'elevator', 'entrance', 'poi'])
const edgeKinds = new Set(['walk', 'stairs', 'elevator'])

/**
 * Проверить граф кампуса до отправки на сервер: те же правила, что у PUT /campuses/{id}/graph,
 * но с понятными сообщениями и до замены графа целиком.
 */
export function validateGraph(data: unknown): { graph: CampusGraph; stats: GraphStats } | { error: string } {
  if (typeof data !== 'object' || data === null) return { error: 'Файл должен содержать объект JSON' }
  const graph = data as Partial<CampusGraph>
  if (!Array.isArray(graph.buildings) || !Array.isArray(graph.edges)) {
    return { error: 'Нужны поля buildings (корпуса) и edges (рёбра)' }
  }
  const keys = new Set<string>()
  const stats: GraphStats = { buildings: graph.buildings.length, floors: 0, nodes: 0, edges: graph.edges.length, rooms: 0 }
  for (const building of graph.buildings) {
    if (!building?.slug || !building.name || !Array.isArray(building.floors)) {
      return { error: 'У каждого корпуса нужны slug, name и floors' }
    }
    for (const floor of building.floors) {
      if (!Number.isInteger(floor?.level) || !Array.isArray(floor.nodes)) {
        return { error: `Корпус ${building.slug}: у этажа нужны целый level и список nodes` }
      }
      stats.floors += 1
      for (const node of floor.nodes) {
        if (!node?.key || typeof node.x !== 'number' || typeof node.y !== 'number') {
          return { error: `Корпус ${building.slug}, этаж ${floor.level}: у узла нужны key, x и y` }
        }
        if (!nodeKinds.has(node.kind)) return { error: `Узел ${node.key}: неизвестный тип «${String(node.kind)}»` }
        if (keys.has(node.key)) return { error: `Повторяется ключ узла ${node.key}` }
        keys.add(node.key)
        stats.nodes += 1
        if (node.kind === 'room') stats.rooms += 1
      }
    }
  }
  for (const edge of graph.edges) {
    if (!edge || !keys.has(edge.a) || !keys.has(edge.b)) {
      return { error: `Ребро ссылается на неизвестный узел: ${edge?.a ?? '?'} – ${edge?.b ?? '?'}` }
    }
    if (edge.kind !== undefined && !edgeKinds.has(edge.kind)) {
      return { error: `Ребро ${edge.a} – ${edge.b}: неизвестный тип «${String(edge.kind)}»` }
    }
  }
  return { graph: graph as CampusGraph, stats }
}
