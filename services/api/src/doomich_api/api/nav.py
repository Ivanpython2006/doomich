"""Навигация по кампусу (R2): карта, маршрут, определение места по фото или описанию."""

from __future__ import annotations

import uuid

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.api.deps import current_user, user_session
from doomich_api.config import get_settings
from doomich_api.context import UserContext
from doomich_api.models import Building, Campus, Floor, NavEdge, NavNode
from doomich_api.nav.routing import describe_route, find_node, load_graph, shortest_path

router = APIRouter(prefix="/v1", tags=["navigation"])


class FloorOut(BaseModel):
    id: uuid.UUID
    level: int
    name: str | None


class BuildingOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    floors: list[FloorOut]


class CampusOut(BaseModel):
    id: uuid.UUID
    slug: str
    name: str
    buildings: list[BuildingOut]


class RouteIn(BaseModel):
    destination: str = Field(max_length=100)
    origin: str = Field(max_length=100)
    accessible: bool = False


class RouteOut(BaseModel):
    length_m: float
    steps: list[str]
    path: list[dict]


@router.get("/campus", response_model=list[CampusOut])
async def campus(user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)):
    campuses = (await session.execute(select(Campus).where(Campus.university_id == user.university_id))).scalars()
    result = []
    for c in campuses:
        buildings = []
        for b in (await session.execute(select(Building).where(Building.campus_id == c.id))).scalars():
            floors = (
                await session.execute(select(Floor).where(Floor.building_id == b.id).order_by(Floor.level))
            ).scalars()
            buildings.append(
                BuildingOut(
                    id=b.id,
                    slug=b.slug,
                    name=b.name,
                    floors=[FloorOut(id=f.id, level=f.level, name=f.name) for f in floors],
                )
            )
        result.append(CampusOut(id=c.id, slug=c.slug, name=c.name, buildings=buildings))
    return result


@router.get("/campus/floors/{floor_id}/graph")
async def floor_graph(
    floor_id: uuid.UUID, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    floor = await session.get(Floor, floor_id)
    if floor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Этаж не найден")
    building = await session.get(Building, floor.building_id)
    campus_row = await session.get(Campus, building.campus_id)
    if campus_row.university_id != user.university_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Этаж не найден")
    nodes = list((await session.execute(select(NavNode).where(NavNode.floor_id == floor.id))).scalars())
    ids = {n.id for n in nodes}
    edges = (await session.execute(select(NavEdge).where(NavEdge.from_id.in_(ids)))).scalars()
    return {
        "floor": {"id": str(floor.id), "level": floor.level, "meters_per_px": floor.meters_per_px},
        "nodes": [
            {"id": str(n.id), "key": n.key, "kind": n.kind, "name": n.name, "room": n.room, "x": n.x, "y": n.y}
            for n in nodes
        ],
        "edges": [
            {"from": str(e.from_id), "to": str(e.to_id), "kind": e.kind, "length_m": e.length_m}
            for e in edges
            if e.to_id in ids
        ],
    }


@router.post("/nav/route", response_model=RouteOut)
async def route(
    body: RouteIn, user: UserContext = Depends(current_user), session: AsyncSession = Depends(user_session)
):
    graph = await load_graph(session, user.university_id)
    start, goal = find_node(graph, body.origin), find_node(graph, body.destination)
    if start is None or goal is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Точка не найдена на карте")
    found = shortest_path(graph, start.id, goal.id, accessible_only=body.accessible)
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Маршрут не найден")
    path, length = found
    return RouteOut(
        length_m=round(length, 1),
        steps=describe_route(graph, path, locale=user.locale),
        path=[
            {
                "id": str(n),
                "key": graph.nodes[n].key,
                "floor": graph.nodes[n].floor_level,
                "x": graph.nodes[n].x,
                "y": graph.nodes[n].y,
            }
            for n in path
        ],
    )


@router.post("/nav/locate")
async def locate(
    campus_slug: str = Form(...),
    text: str | None = Form(None, max_length=500),
    images: list[UploadFile] | None = File(None),
    user: UserContext = Depends(current_user),
):
    """Где я? Кадры камеры (до 8) или текстовое описание → кандидаты узлов графа.

    Кадры передаются сервису навигации и не сохраняются.
    """
    if not text and not images:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Нужны кадры или описание")
    files = []
    for image in (images or [])[:8]:
        files.append(
            (
                "images",
                (image.filename or "frame.jpg", await image.read(3 * 1024 * 1024), image.content_type or "image/jpeg"),
            )
        )
    data = {"tenant": user.university_slug, "campus": campus_slug}
    if text:
        data["text"] = text
    async with httpx.AsyncClient(timeout=30) as client:
        try:
            resp = await client.post(f"{get_settings().nav_base_url}/v1/locate", data=data, files=files or None)
        except httpx.HTTPError as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Сервис навигации недоступен") from exc
    if resp.status_code >= 400:
        raise HTTPException(resp.status_code, resp.json().get("detail", "Ошибка навигации"))
    return resp.json()
