from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.agents.analysis_graph import resume_analysis_graph
from app.services.pdf_extractor import extract_text_from_pdf

router = APIRouter()


@router.post("/report")
async def generate_analysis_report(
    file: UploadFile = File(...),
    include_raw_news: bool = Form(False),
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

    initial_state = {
        "resume_text": resume_text,
        "resume_profile": None,
        "matched_news": None,
        "relevance_analysis": None,
        "swot": None,
        "final_report": None,
        "error": None,
    }

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
        "resume_profile": result["resume_profile"],
        "matched_news_count": len(slim_news),
        "matched_news": slim_news,
        "raw_matched_news": result["matched_news"] if include_raw_news else None,
        "relevance_analysis": result["relevance_analysis"],
        "swot": result["swot"],
        "final_report": result["final_report"],
    }
