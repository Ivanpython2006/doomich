"""Гибридный поиск: векторы (pgvector) + полнотекст (PostgreSQL FTS) → RRF → реранкер."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from doomich_api.ai.retrieval_models import Reranker
from doomich_api.models import Chunk, Document

RRF_K = 60
log = logging.getLogger(__name__)


@dataclass
class SearchScope:
    university_id: uuid.UUID
    user_id: uuid.UUID | None = None
    include_user: bool = True
    include_university: bool = False
    course_ids: list[uuid.UUID] = field(default_factory=list)
    document_ids: list[uuid.UUID] | None = None


@dataclass
class Hit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    owner_type: str
    page: int | None
    section: str | None
    body: str
    score: float
    title: str = ""


def _conditions(scope: SearchScope, embed_model: str):
    parts = []
    if scope.include_user and scope.user_id is not None:
        parts.append(and_(Chunk.owner_type == "user", Chunk.user_id == scope.user_id))
    if scope.include_university:
        parts.append(and_(Chunk.owner_type == "university", Chunk.university_id == scope.university_id))
    if scope.course_ids:
        parts.append(and_(Chunk.owner_type == "course", Chunk.course_id.in_(scope.course_ids)))
    if not parts:
        return None
    cond = and_(or_(*parts), Chunk.embed_model == embed_model)
    if scope.document_ids:
        cond = and_(cond, Chunk.document_id.in_(scope.document_ids))
    return cond


async def hybrid_search(
    session: AsyncSession,
    *,
    scope: SearchScope,
    query: str,
    query_vec: list[float],
    embed_model: str,
    reranker: Reranker | None = None,
    limit: int = 6,
    candidates: int = 30,
    title_of: Callable[[Document], str] | None = None,
) -> list[Hit]:
    cond = _conditions(scope, embed_model)
    if cond is None or not query.strip():
        return []

    cols = (Chunk.id, Chunk.document_id, Chunk.owner_type, Chunk.page, Chunk.section, Chunk.body)

    # 1) векторный поиск: сначала фильтр (MATERIALIZED), потом точное ранжирование —
    #    так результаты не теряются из-за фильтрации после HNSW
    scoped = select(*cols, Chunk.embedding).where(cond).cte("scoped").prefix_with("MATERIALIZED")
    distance = scoped.c.embedding.cosine_distance(query_vec)
    vec_rows = (
        await session.execute(
            select(*(scoped.c[c.key] for c in cols), (1 - distance).label("score")).order_by(distance).limit(candidates)
        )
    ).all()

    # 2) полнотекстовый поиск на русском и английском
    tsq = func.websearch_to_tsquery("russian", query).op("||")(func.websearch_to_tsquery("english", query))
    rank = func.ts_rank_cd(Chunk.fts, tsq)
    fts_rows = (
        await session.execute(
            select(*cols, rank.label("score"))
            .where(cond, Chunk.fts.op("@@")(tsq))
            .order_by(rank.desc())
            .limit(candidates)
        )
    ).all()

    # 3) слияние Reciprocal Rank Fusion
    fused: dict[uuid.UUID, Hit] = {}
    scores: dict[uuid.UUID, float] = {}
    for rows in (vec_rows, fts_rows):
        for rank_pos, row in enumerate(rows):
            scores[row.id] = scores.get(row.id, 0.0) + 1.0 / (RRF_K + rank_pos + 1)
            fused.setdefault(
                row.id,
                Hit(row.id, row.document_id, row.owner_type, row.page, row.section, row.body, 0.0),
            )
    hits = sorted(fused.values(), key=lambda h: scores[h.chunk_id], reverse=True)[: max(limit * 3, limit)]
    for hit in hits:
        hit.score = scores[hit.chunk_id]

    # 4) реранкер уточняет порядок
    if reranker is not None and hits:
        try:
            rr = await reranker.rerank(query, [h.body for h in hits])
            for hit, value in zip(hits, rr, strict=True):
                hit.score = value
            hits.sort(key=lambda h: h.score, reverse=True)
        except Exception:  # без реранкера поиск всё равно работает
            log.warning("Реранкер недоступен, используем порядок RRF", exc_info=True)
    hits = hits[:limit]

    if hits:
        docs = (await session.execute(select(Document).where(Document.id.in_({h.document_id for h in hits})))).scalars()
        titles = {d.id: (title_of(d) if title_of else (d.title or "")) for d in docs}
        for hit in hits:
            hit.title = titles.get(hit.document_id, "")
    return hits


def format_hits_for_llm(hits: list[Hit], start: int = 1) -> str:
    """Нумерованные фрагменты, на которые модель ссылается как [n]."""
    if not hits:
        return "Ничего не найдено."
    lines = []
    for i, hit in enumerate(hits, start=start):
        where = f", стр. {hit.page}" if hit.page else ""
        section = f" — {hit.section}" if hit.section else ""
        lines.append(f"[{i}] «{hit.title}»{where}{section}\n{hit.body}")
    return "\n\n".join(lines)
