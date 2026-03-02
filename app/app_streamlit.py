"""
NewStrackers AI - Main Streamlit Application
AI-Powered Job Interview and Career Development Platform
"""

import logging

import streamlit as st

from app.core.config import settings
from app.core.constants import DEFAULT_INDUSTRIES
from app.core.dependencies import get_company_analyzer, get_industry_analyzer
from app.visualization.plotly_viz import create_radar_chart, create_sentiment_heatmap
from app.visualization.wordcloud_viz import create_wordcloud

# Setup logging
logging.basicConfig(
    level=settings.LOG_LEVEL,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Page configuration
st.set_page_config(
    page_title="NewStrackers AI",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        color: #1f77b4;
        margin-bottom: 10px;
    }
    .sub-header {
        font-size: 1.2rem;
        color: #555;
        margin-bottom: 30px;
    }
</style>
""", unsafe_allow_html=True)


def main():
    """Main application"""
    
    # Header
    st.markdown("<div class='main-header'>📰 NewStrackers AI</div>", unsafe_allow_html=True)
    st.markdown(
        "<div class='sub-header'>자소서 기반 맞춤형 산업 분석 및 면접 준비 플랫폼</div>",
        unsafe_allow_html=True
    )
    
    # Sidebar Configuration
    st.sidebar.subheader("⚙️ 분석 설정")
    
    # Analysis type selection
    analysis_type = st.sidebar.radio(
        "분석 유형 선택",
        ["산업 트렌드 분석", "기업 면접 준비"]
    )
    
    # Common settings
    days_back = st.sidebar.slider(
        "분석 기간 (일)",
        min_value=30,
        max_value=365,
        value=365,
        step=30
    )
    
    # ====================================================================
    # 1. INDUSTRY TREND ANALYSIS
    # ====================================================================
    if analysis_type == "산업 트렌드 분석":
        st.sidebar.subheader("산업 선택")
        
        selected_industry = st.sidebar.selectbox(
            "분석할 산업",
            options=DEFAULT_INDUSTRIES,
            index=0
        )
        
        # Analyze button
        if st.sidebar.button("🔍 분석 시작", key="industry_analyze"):
            with st.spinner("산업 데이터를 분석 중입니다..."):
                try:
                    analysis_result = get_industry_analyzer().analyze(
                        industry=selected_industry,
                        days_back=days_back
                    )
                    
                    # Store in session state for display
                    st.session_state.industry_analysis = analysis_result
                    st.session_state.show_industry_results = True
                    
                except Exception as e:
                    logger.error(f"Industry analysis error: {e}")
                    st.error(f"분석 중 오류가 발생했습니다: {str(e)}")
        
        # Display results if available
        if st.session_state.get("show_industry_results"):
            analysis = st.session_state.industry_analysis
            
            st.success(f"✅ {analysis.industry} 산업 분석 완료")
            st.subheader(f"📊 {analysis.industry} 산업 분석 결과")
            
            # Display tabs
            tab1, tab2, tab3, tab4 = st.tabs(
                ["📈 주요 트렌드", "☁️ 키워드 맵", "📉 감정 분석", "📰 데이터 통계"]
            )
            
            with tab1:
                st.subheader("🎯 주요 트렌드 (3가지)")
                for i, trend in enumerate(analysis.trends, 1):
                    st.markdown(f"**{i}. {trend}**")
            
            with tab2:
                st.subheader("☁️ 산업 키워드 맵")
                if analysis.keywords:
                    wordcloud_fig = create_wordcloud(analysis.keywords)
                    st.plotly_chart(wordcloud_fig, use_container_width=True)
                else:
                    st.info("키워드 데이터가 없습니다.")
            
            with tab3:
                st.subheader("📉 월별 감정 지수 분석")
                if analysis.monthly_sentiment:
                    heatmap_fig = create_sentiment_heatmap(analysis.monthly_sentiment)
                    st.plotly_chart(heatmap_fig, use_container_width=True)
                else:
                    st.info("감정 분석 데이터가 없습니다.")
            
            with tab4:
                st.subheader("📊 데이터 통계")
                if analysis.source_stats:
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("총 뉴스 기사", analysis.source_stats.total_articles)
                    with col2:
                        st.metric("분석 기간", f"{analysis.source_stats.date_range_days}일")
                    with col3:
                        st.metric("마지막 업데이트", 
                                 analysis.source_stats.last_updated.strftime("%m월 %d일"))
                    
                    st.markdown("**상위 뉴스 출처**")
                    for source in analysis.source_stats.top_sources:
                        st.markdown(f"- {source}")
    
    # ====================================================================
    # 2. COMPANY INTERVIEW PREPARATION
    # ====================================================================
    else:  # 기업 면접 준비
        col1, col2 = st.sidebar.columns(2)
        
        with col1:
            selected_industry = st.sidebar.selectbox(
                "산업 선택",
                options=DEFAULT_INDUSTRIES,
                index=0
            )
        
        with col2:
            company_name = st.sidebar.text_input(
                "기업명",
                value="삼성전자",
                placeholder="분석할 기업명을 입력하세요"
            )
        
        st.sidebar.subheader("📄 자소서/이력서")
        resume_text = st.sidebar.text_area(
            "자소서 또는 이력서 입력",
            placeholder="당신의 경력, 기술, 성과를 입력해주세요...",
            height=150,
            value="""삼성전자 S/W개발자 지원자입니다.
- 5년 경력, Python, C++ 전문
- 메모리칩 최적화 프로젝트 리드
- AI/ML 프로젝트 경험"""
        )
        
        # Analyze button
        if st.sidebar.button("🔍 면접 준비 분석", key="company_analyze"):
            if not resume_text or len(resume_text) < 10:
                st.sidebar.error("자소서를 입력해주세요 (최소 10글자)")
            elif not company_name:
                st.sidebar.error("기업명을 입력해주세요")
            else:
                with st.spinner("기업 정보를 분석 중입니다..."):
                    try:
                        analysis_result = get_company_analyzer().analyze(
                            company=company_name,
                            industry=selected_industry,
                            resume=resume_text,
                            days_back=days_back
                        )
                        
                        st.session_state.company_analysis = analysis_result
                        st.session_state.show_company_results = True
                        
                    except Exception as e:
                        logger.error(f"Company analysis error: {e}")
                        st.error(f"분석 중 오류가 발생했습니다: {str(e)}")
        
        # Display results if available
        if st.session_state.get("show_company_results"):
            analysis = st.session_state.company_analysis
            
            st.success(f"✅ {analysis.company} 면접 준비 분석 완료")
            st.subheader(f"💼 {analysis.company} 톺아보기")
            
            # Display tabs
            tab1, tab2, tab3, tab4, tab5 = st.tabs(
                ["💡 회사 개요", "📊 5대 지표", "🎯 SWOT", "❓ 킬러 문항", "⚠️ 리스크 분석"]
            )
            
            with tab1:
                st.subheader("회사 정보")
                if analysis.company_info:
                    st.write(analysis.company_info.description)
                
                st.subheader("최근 뉴스 주제")
                for theme in analysis.recent_news_themes:
                    st.markdown(f"- {theme}")
            
            with tab2:
                st.subheader("5대 지표 분석 (Radar Chart)")
                st.markdown("""
                - **성장성**: 매출, 시장 확대
                - **안정성**: 일관된 성과, 위기 관리
                - **혁신성**: R&D, 신기술
                - **ESG**: 환경, 사회 책임
                - **시장점유율**: 경쟁력, 리더십
                """)
                
                if analysis.radar_chart:
                    radar_fig = create_radar_chart(analysis.radar_chart)
                    st.plotly_chart(radar_fig, use_container_width=True)
            
            with tab3:
                st.subheader("🎯 SWOT 분석")
                
                s_col, w_col = st.columns(2)
                with s_col:
                    st.markdown("#### 💪 강점 (Strengths)")
                    st.write(analysis.swot.strengths)
                
                with w_col:
                    st.markdown("#### ⚠️ 약점 (Weaknesses)")
                    st.write(analysis.swot.weaknesses)
                
                o_col, t_col = st.columns(2)
                with o_col:
                    st.markdown("#### 🚀 기회 (Opportunities)")
                    st.write(analysis.swot.opportunities)
                
                with t_col:
                    st.markdown("#### 🔴 위협 (Threats)")
                    st.write(analysis.swot.threats)
            
            with tab4:
                st.subheader("❓ 실전 면접 질문 & 답안 가이드")
                
                for i, qna in enumerate(analysis.interview_qna, 1):
                    with st.expander(
                        f"**Q{i}. {qna.question[:50]}...**",
                        expanded=(i == 1)
                    ):
                        st.markdown(f"**질문 배경**: {qna.context or '기본 평가'}")
                        st.markdown(f"**난이도**: {qna.difficulty.upper()}")
                        st.markdown(f"**답변 가이드**\n\n{qna.guide}")
            
            with tab5:
                st.subheader("⚠️ 기업 리스크 & 기회 분석")
                
                risk_col, opp_col = st.columns(2)
                
                with risk_col:
                    st.markdown("### 🔴 주요 리스크")
                    for risk in analysis.risk_assessment.critical_risks:
                        st.markdown(f"- {risk}")
                
                with opp_col:
                    st.markdown("### 🟢 성장 기회")
                    for opp in analysis.risk_assessment.growth_opportunities:
                        st.markdown(f"- {opp}")
                
                st.markdown("### 📌 추천 포커스")
                st.info(analysis.risk_assessment.recommended_focus)


if __name__ == "__main__":
    # Initialize session state
    if "show_industry_results" not in st.session_state:
        st.session_state.show_industry_results = False
    if "show_company_results" not in st.session_state:
        st.session_state.show_company_results = False
    
    try:
        main()
    except Exception as e:
        logger.error(f"Application error: {e}")
        st.error(f"애플리케이션 오류: {str(e)}")
