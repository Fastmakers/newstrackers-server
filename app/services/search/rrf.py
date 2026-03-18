"""
RRF (Reciprocal Rank Fusion) — 벡터 검색 + 키워드 검색 결과 융합.

SPEC: docs/SPEC_SEARCH.md §4-2

알고리즘:
    score(d) = Σ 1 / (k + rank_i(d))    k=60 (표준값)

두 결과 리스트(벡터, 키워드)의 chunk_id 기준으로 점수를 합산해
상위 N건을 반환한다.
"""

from __future__ import annotations

from app.schemas.data_models import NewsChunk

_K = 60  # RRF 표준 상수


def rrf_fuse_multi(
    result_lists: list[list[NewsChunk]],
    top_n: int = 100,
) -> list[NewsChunk]:
    """N개의 순위 리스트를 RRF로 융합해 상위 top_n 청크를 반환."""
    scores: dict[int, float] = {}
    chunk_map: dict[int, NewsChunk] = {}
    for results in result_lists:
        for rank, chunk in enumerate(results, start=1):
            scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (_K + rank)
            chunk_map.setdefault(chunk.id, chunk)
    top_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:top_n]
    return [chunk_map[cid] for cid in top_ids]


def rrf_fuse(
    vector_results: list[NewsChunk],
    keyword_results: list[NewsChunk],
    top_n: int = 100,
) -> list[NewsChunk]:
    """두 순위 리스트를 RRF로 융합해 상위 top_n 청크를 반환.

    - vector_results: 벡터 유사도 순 NewsChunk 리스트
    - keyword_results: 키워드 관련도 순 NewsChunk 리스트
    - 두 리스트에 모두 없는 청크도 한쪽만 있으면 포함
    - 동일 chunk_id가 여러 번 나와도 점수 누적
    """
    scores: dict[int, float] = {}
    chunk_map: dict[int, NewsChunk] = {}

    for rank, chunk in enumerate(vector_results, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (_K + rank)
        chunk_map[chunk.id] = chunk

    for rank, chunk in enumerate(keyword_results, start=1):
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1.0 / (_K + rank)
        chunk_map.setdefault(chunk.id, chunk)

    top_ids = sorted(scores, key=scores.__getitem__, reverse=True)[:top_n]
    return [chunk_map[cid] for cid in top_ids]
