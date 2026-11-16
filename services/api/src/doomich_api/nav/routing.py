"""Маршруты по графу кампуса (R2): Дейкстра с переходами между этажами и режимом доступной среды."""

from __future__ import annotations

import heapq
import itertools
import math
import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.models import Building, Campus, Floor, NavEdge, NavNode

ELEVATOR_PENALTY_M = 15.0  # ожидание лифта в «метрах»


@dataclass
class Node:
    id: uuid.UUID
    key: str
    kind: str
    name: str | None
    room: str | None
    x: float
    y: float
    floor_level: int
    building: str
    tags: list[str]


@dataclass
class Graph:
    nodes: dict[uuid.UUID, Node] = field(default_factory=dict)
    adj: dict[uuid.UUID, list[tuple[uuid.UUID, float, str, bool]]] = field(default_factory=dict)

    def add_edge(self, a: uuid.UUID, b: uuid.UUID, length: float, kind: str, accessible: bool) -> None:
        self.adj.setdefault(a, []).append((b, length, kind, accessible))
        self.adj.setdefault(b, []).append((a, length, kind, accessible))


async def load_graph(session: AsyncSession, university_id: uuid.UUID) -> Graph:
    graph = Graph()
    rows = await session.execute(
        select(NavNode, Floor.level, Building.name)
        .join(Floor, NavNode.floor_id == Floor.id)
        .join(Building, Floor.building_id == Building.id)
        .join(Campus, Building.campus_id == Campus.id)
        .where(Campus.university_id == university_id)
    )
    for node, level, building in rows:
        graph.nodes[node.id] = Node(
            node.id, node.key, node.kind, node.name, node.room, node.x, node.y, level, building, list(node.tags or [])
        )
    if not graph.nodes:
        return graph
    edges = await session.execute(select(NavEdge).where(NavEdge.from_id.in_(graph.nodes)))
    for edge in edges.scalars():
        if edge.to_id in graph.nodes:
            graph.add_edge(edge.from_id, edge.to_id, edge.length_m, edge.kind, edge.accessible)
    return graph


def _norm(text: str) -> str:
    return "".join(text.lower().split()).replace("ауд.", "").replace("аудитория", "")


def find_node(graph: Graph, query: str) -> Node | None:
    q = _norm(query)
    if not q:
        return None
    for node in graph.nodes.values():
        if node.room and _norm(node.room) == q:
            return node
    for node in graph.nodes.values():
        if node.key.lower() == query.lower():
            return node
    for node in graph.nodes.values():
        haystack = " ".join(filter(None, [node.name or "", *node.tags])).lower()
        if query.lower().strip() and query.lower().strip() in haystack:
            return node
    return None


def shortest_path(
    graph: Graph, start: uuid.UUID, goal: uuid.UUID, *, accessible_only: bool = False
) -> tuple[list[uuid.UUID], float] | None:
    dist = {start: 0.0}
    prev: dict[uuid.UUID, uuid.UUID] = {}
    queue = [(0.0, str(start), start)]
    while queue:
        d, _, node = heapq.heappop(queue)
        if node == goal:
            path = [goal]
            while path[-1] != start:
                path.append(prev[path[-1]])
            return path[::-1], d
        if d > dist.get(node, math.inf):
            continue
        for nxt, length, kind, accessible in graph.adj.get(node, []):
            if accessible_only and (not accessible or kind == "stairs"):
                continue
            cost = length + (ELEVATOR_PENALTY_M if kind == "elevator" else 0.0)
            nd = d + cost
            if nd < dist.get(nxt, math.inf):
                dist[nxt] = nd
                prev[nxt] = node
                heapq.heappush(queue, (nd, str(nxt), nxt))
    return None


def _label(node: Node, ru: bool) -> str:
    if node.room:
        return f"аудитория {node.room}" if ru else f"room {node.room}"
    return node.name or node.key


def describe_route(graph: Graph, path: list[uuid.UUID], *, locale: str = "ru") -> list[str]:
    """Сжать путь в понятные шаги с ориентирами."""
    ru = not locale.startswith("en")
    steps: list[str] = []
    walked = 0.0
    for a_id, b_id in itertools.pairwise(path):
        a, b = graph.nodes[a_id], graph.nodes[b_id]
        length = next((ln for n, ln, _k, _acc in graph.adj[a_id] if n == b_id), 0.0)
        if a.floor_level != b.floor_level:
            if walked:
                steps.append(f"Пройдите около {round(walked)} м" if ru else f"Walk about {round(walked)} m")
                walked = 0.0
            how = (
                ("на лифте" if "elevator" in (a.kind, b.kind) else "по лестнице")
                if ru
                else ("by elevator" if "elevator" in (a.kind, b.kind) else "by the stairs")
            )
            verb = (
                ("Поднимитесь" if b.floor_level > a.floor_level else "Спуститесь")
                if ru
                else ("Go up" if b.floor_level > a.floor_level else "Go down")
            )
            steps.append(f"{verb} {how} на {b.floor_level} этаж" if ru else f"{verb} {how} to floor {b.floor_level}")
            continue
        walked += length
        if b.kind in {"poi", "entrance"} and b.name and b_id != path[-1]:
            steps.append(
                (f"Пройдите около {round(walked)} м до ориентира «{b.name}»")
                if ru
                else f"Walk about {round(walked)} m to «{b.name}»"
            )
            walked = 0.0
    if walked:
        steps.append(f"Пройдите около {round(walked)} м" if ru else f"Walk about {round(walked)} m")
    goal = graph.nodes[path[-1]]
    steps.append(f"Вы на месте: {_label(goal, ru)}" if ru else f"You have arrived: {_label(goal, ru)}")
    return steps
