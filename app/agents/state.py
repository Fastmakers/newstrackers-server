from typing import Optional, TypedDict


class ResumeProfile(TypedDict):
    """Node 1에서 자소서로부터 추출한 지원자 정보"""

    job_title: str           # 지원 직무 (예: "백엔드 개발자")
    industry: str            # INDUSTRY_KEYWORDS 중 하나 (예: "AI 인공지능")
    company: str             # 지원 회사 (없으면 빈 문자열)
    skills: list[str]        # 보유 스킬/역량 (예: ["Python", "FastAPI"])
    experiences: list[str]   # 경험/프로젝트 (예: ["스타트업 서버 개발 2년"])


class AnalysisState(TypedDict):
    """LangGraph 파이프라인 전체 상태"""

    # 입력 (PDF 추출 텍스트)
    resume_text: str

    # Node 1 출력: 자소서 분석
    resume_profile: Optional[ResumeProfile]

    # Node 2 출력: 키워드 매칭 뉴스
    matched_news: Optional[list[dict]]

    # Node 3 출력: 관련성 분석
    relevance_analysis: Optional[str]

    # Node 4 출력: SWOT + 종합 리포트
    swot: Optional[dict[str, list[str]]]
    final_report: Optional[str]

    # 에러 메시지 (None이면 성공)
    error: Optional[str]
