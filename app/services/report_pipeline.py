"""리포트 파이프라인 — PDF 텍스트 → ReportResponse 오케스트레이션.

엔드포인트(/report, /report/stream)에서 공유하는 비즈니스 로직 계층.
HTTP 관련 코드(파일 파싱, HTTPException 등)는 포함하지 않는다.

Pipeline steps:
    1. analyze_resume + transform_query  (병렬)
    2. hybrid_search
    3. generate_swot_list + generate_relevance_analysis  (병렬)
    4. generate_final_report
    5. ReportResponse 조립
"""

import asyncio
import functools
import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from app.schemas.data_models import MatchedNewsItem, ReportResponse, ResumeProfile, SWOTList
from app.services.news_service import NewsService
from app.services.report_generator import ReportGenerator
from app.services.resume_analyzer import ResumeAnalyzer

logger = logging.getLogger(__name__)


@dataclass
class ReportInput:
    """파이프라인 입력 파라미터."""

    resume_text: str
    company: str = ""
    job_title: str = ""
    industry: str = ""
    career_level: str = "신입"  # "신입" | "경력"


class ReportPipeline:
    """취업 전략 리포트 파이프라인."""

    def __init__(
        self,
        news_service: NewsService,
        resume_analyzer: ResumeAnalyzer,
        report_generator: ReportGenerator,
    ):
        self._news = news_service
        self._resume = resume_analyzer
        self._report = report_generator

    # ------------------------------------------------------------------
    # 공유 헬퍼
    # ------------------------------------------------------------------

    def _build_search_input(self, inp: ReportInput) -> str:
        base = inp.resume_text[:1500]
        if inp.company or inp.job_title:
            base = f"지원 기업: {inp.company}\n지원 직무: {inp.job_title}\n\n" + base
        return base

    def _build_matched_news(self, chunks: list) -> list[MatchedNewsItem]:
        result: list[MatchedNewsItem] = []
        for chunk in chunks:
            article = chunk.article
            if article is None:
                continue
            distance = getattr(chunk, "distance", 0.0) or 0.0
            result.append(MatchedNewsItem(
                id=article.id,
                title=article.title,
                job_category=article.category_l2 or "",
                published_at=article.published_at,
                url=article.article_url or "",
                distance=float(distance),
            ))
        return result

    def _assemble(
        self,
        resume_profile: ResumeProfile,
        matched_news: list[MatchedNewsItem],
        swot_dict: dict,
        relevance_analysis: str,
        final_report: str,
    ) -> ReportResponse:
        return ReportResponse(
            resume_profile=resume_profile,
            matched_news=matched_news,
            matched_news_count=len(matched_news),
            relevance_analysis=relevance_analysis,
            swot=SWOTList(
                strengths=swot_dict.get("strengths", []),
                weaknesses=swot_dict.get("weaknesses", []),
                opportunities=swot_dict.get("opportunities", []),
                threats=swot_dict.get("threats", []),
            ),
            final_report=final_report,
        )

    # ------------------------------------------------------------------
    # 동기 실행 — POST /report
    # ------------------------------------------------------------------

    def run(self, inp: ReportInput) -> ReportResponse:
        """파이프라인 동기 실행. 블로킹 I/O이므로 threadpool에서 호출하세요."""
        search_input = self._build_search_input(inp)

        # Step 1: analyze_resume + transform_query (병렬)
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_resume = ex.submit(self._resume.analyze_resume, inp.resume_text)
            f_query = ex.submit(self._resume.transform_query, search_input)
            raw_resume = f_resume.result()
            transformed = f_query.result()

        resolved_job_title = inp.job_title or raw_resume.get("target_role") or ""
        resume_profile = ResumeProfile(
            company=inp.company,
            job_title=resolved_job_title,
            industry=inp.industry,
            skills=raw_resume.get("skills") or [],
            experiences=raw_resume.get("experience_keywords") or [],
        )

        search_query: str = transformed.get("query") or search_input[:200]
        keyword_query: str = inp.company or search_query

        # Step 2: hybrid search
        chunks = self._news.hybrid_search(
            query=search_query, keyword_query=keyword_query, top_k=15
        )
        matched_news = self._build_matched_news(chunks)

        # Step 3: SWOT + relevance (병렬)
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_swot = ex.submit(
                self._report.generate_swot_list,
                inp.resume_text, inp.company, resolved_job_title,
                chunks, inp.industry, inp.career_level,
            )
            f_relevance = ex.submit(
                self._report.generate_relevance_analysis,
                inp.resume_text, chunks, inp.company,
                inp.industry, resolved_job_title, inp.career_level,
            )
            swot_dict = f_swot.result()
            relevance_analysis = f_relevance.result()

        # Step 4: final report
        final_report = self._report.generate_final_report(
            resume=inp.resume_text,
            company=inp.company,
            job_title=resolved_job_title,
            industry=inp.industry,
            swot=swot_dict,
            relevance_analysis=relevance_analysis,
            career_level=inp.career_level,
        )

        return self._assemble(resume_profile, matched_news, swot_dict, relevance_analysis, final_report)

    # ------------------------------------------------------------------
    # 비동기 스트리밍 — POST /report/stream
    # ------------------------------------------------------------------

    async def stream(self, inp: ReportInput):
        """파이프라인 비동기 스트리밍 (AsyncGenerator[str]).

        엔드포인트에서 step 1 (PDF 파싱) 이후 이 메서드를 호출해 SSE 이벤트를 yield한다.

        이벤트 형식:
            {"type": "progress", "step": 2..6, "status": "start"|"done", "label": "...", "detail": "..."}
            {"type": "result",   "data": {...ReportResponse...}}
            {"type": "error",    "message": "..."}
        """
        loop = asyncio.get_running_loop()
        search_input = self._build_search_input(inp)

        def _emit(step: int, label: str, s: str = "start", detail: str = "") -> str:
            msg: dict = {"type": "progress", "step": step, "status": s, "label": label}
            if detail:
                msg["detail"] = detail
            return f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"

        def _emit_partial(field: str, data) -> str:
            msg: dict = {"type": "partial", "field": field, "data": data}
            if field == "matched_news" and isinstance(data, list):
                msg["count"] = len(data)
            return f"data: {json.dumps(msg, ensure_ascii=False, default=str)}\n\n"

        try:
            # Step 2 ‖ 3: analyze + transform (병렬)
            yield _emit(2, "자소서 AI 분석 중...")
            yield _emit(3, "검색 쿼리 최적화 중...")
            raw_resume, transformed = await asyncio.gather(
                loop.run_in_executor(None, self._resume.analyze_resume, inp.resume_text),
                loop.run_in_executor(None, self._resume.transform_query, search_input),
            )
            resolved_job_title = inp.job_title or raw_resume.get("target_role") or ""
            resolved_skills: list[str] = raw_resume.get("skills") or []
            resolved_experiences: list[str] = raw_resume.get("experience_keywords") or []
            resume_profile = ResumeProfile(
                company=inp.company, job_title=resolved_job_title,
                industry=inp.industry, skills=resolved_skills, experiences=resolved_experiences,
            )
            search_query: str = transformed.get("query") or search_input[:200]
            keyword_query: str = inp.company or search_query
            yield _emit(2, "자소서 분석 완료", "done", f"스킬 {len(resolved_skills)}개 추출")
            yield _emit(3, "검색 쿼리 최적화 완료", "done")
            yield _emit_partial("resume_profile", resume_profile.model_dump(mode="json"))

            # Step 4: hybrid search
            yield _emit(4, "관련 뉴스 하이브리드 검색 중...")
            chunks = await loop.run_in_executor(
                None,
                functools.partial(
                    self._news.hybrid_search,
                    query=search_query, keyword_query=keyword_query, top_k=15,
                ),
            )
            matched_news = self._build_matched_news(chunks)
            yield _emit(4, "뉴스 검색 완료", "done", f"{len(matched_news)}건 매칭")
            yield _emit_partial("matched_news", [n.model_dump(mode="json") for n in matched_news])

            # Step 5: SWOT + relevance (병렬)
            yield _emit(5, "SWOT + 산업 연관성 분석 중...")
            swot_dict, relevance_analysis = await asyncio.gather(
                loop.run_in_executor(None, functools.partial(
                    self._report.generate_swot_list,
                    inp.resume_text, inp.company, resolved_job_title,
                    chunks, inp.industry, inp.career_level,
                )),
                loop.run_in_executor(None, functools.partial(
                    self._report.generate_relevance_analysis,
                    inp.resume_text, chunks, inp.company,
                    inp.industry, resolved_job_title, inp.career_level,
                )),
            )
            yield _emit(5, "SWOT + 산업 분석 완료", "done")
            yield _emit_partial("swot", swot_dict)
            yield _emit_partial("relevance_analysis", relevance_analysis)

            # Step 6: final report — 토큰 단위 스트리밍
            yield _emit(6, "최종 면접 리포트 생성 중...")
            token_queue: asyncio.Queue = asyncio.Queue()
            tokens: list[str] = []

            def _produce_tokens() -> None:
                try:
                    for token in self._report.stream_final_report(
                        resume=inp.resume_text, company=inp.company,
                        job_title=resolved_job_title, industry=inp.industry,
                        swot=swot_dict, relevance_analysis=relevance_analysis,
                        career_level=inp.career_level,
                    ):
                        loop.call_soon_threadsafe(token_queue.put_nowait, token)
                except Exception as exc:
                    loop.call_soon_threadsafe(token_queue.put_nowait, exc)
                finally:
                    loop.call_soon_threadsafe(token_queue.put_nowait, None)  # sentinel

            fut = loop.run_in_executor(None, _produce_tokens)
            while True:
                item = await token_queue.get()
                if item is None:
                    break
                if isinstance(item, Exception):
                    raise item
                tokens.append(item)
                yield f"data: {json.dumps({'type': 'token', 'field': 'final_report', 'token': item}, ensure_ascii=False)}\n\n"
            await fut

            final_report = "".join(tokens)
            yield _emit(6, "리포트 생성 완료", "done")

            # 최종 결과 snapshot (하위 호환 — 워커/클라이언트 모두 사용)
            result = self._assemble(resume_profile, matched_news, swot_dict, relevance_analysis, final_report)
            yield (
                f"data: {json.dumps({'type': 'result', 'data': result.model_dump(mode='json')}, ensure_ascii=False, default=str)}\n\n"
            )

        except Exception as exc:
            logger.error("ReportPipeline.stream 오류: %s", exc)
            yield f"data: {json.dumps({'type': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"
