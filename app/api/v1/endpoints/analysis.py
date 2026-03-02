from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agents.analysis_graph import resume_analysis_graph
from app.agents.nodes.analyze_resume import analyze_resume
from app.agents.nodes.match_keywords import match_keywords
from app.services.pdf_extractor import extract_text_from_pdf

router = APIRouter()


@router.post("/report")
async def generate_analysis_report(
    file: UploadFile = File(...),
    include_raw_news: bool = Form(False),
    match_only: bool = Form(False),
    industry: str | None = Form(None),
    company: str | None = Form(None),
    job_title: str | None = Form(None),
):
    """
    자소서 PDF를 업로드하면 LangGraph 파이프라인을 통해 다음을 분석합니다:
    - 자소서 분석 (직무/산업/스킬/경험 추출)
    - 관련 뉴스 매칭 (pgvector 유사도 검색)
    - 산업 동향 및 지원자 연관성 분석
    - SWOT 분석 + 종합 리포트 생성
    """
    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(status_code=415, detail="PDF 파일만 업로드 가능합니다.")

    pdf_bytes = await file.read()

    try:
        resume_text = extract_text_from_pdf(pdf_bytes)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    user_profile_input = {
        k: v.strip()
        for k, v in {
            "industry": industry,
            "company": company,
            "job_title": job_title,
        }.items()
        if v and v.strip()
    }

    initial_state = {
        "resume_text": resume_text,
        "user_profile_input": user_profile_input or None,
        "resume_profile": None,
        "matched_news": None,
        "relevance_analysis": None,
        "swot": None,
        "final_report": None,
        "node_timings_ms": {},
        "error": None,
    }

    if match_only:
        result = await analyze_resume(initial_state)
        if result.get("error"):
            raise HTTPException(status_code=500, detail=result["error"])
        result = await match_keywords(result)
    else:
        result = await resume_analysis_graph.ainvoke(initial_state)

    if result.get("error"):
        raise HTTPException(status_code=500, detail=result["error"])

    # matched_news에서 document(본문 전체) 제외 - 응답 크기 최적화
    slim_news = [
        {
            "id": n["id"],
            "title": n["metadata"]["title"],
            "url": n["metadata"]["url"],
            "job_category": n["metadata"]["job_category"],
            "published_at": n["metadata"]["published_at"],
            "distance": n["distance"],
        }
        for n in (result["matched_news"] or [])
    ]

    return {
        "status": "success",
        "mode": "match_only" if match_only else "full_report",
        "input_profile": user_profile_input or None,
        "resume_profile": result["resume_profile"],
        "matched_news_count": len(slim_news),
        "matched_news": slim_news,
        "raw_matched_news": result["matched_news"] if include_raw_news else None,
        "node_timings_ms": result.get("node_timings_ms"),
        "relevance_analysis": result.get("relevance_analysis"),
        "swot": result.get("swot"),
        "final_report": result.get("final_report"),
    }
