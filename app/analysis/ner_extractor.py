"""
개체명 인식(NER) 및 품사 태깅(POS) 기반 분석기.

kiwipiepy 형태소 분석 결과를 이용해:
    - 조직(ORG): 기업·기관·단체
    - 인물(PERSON): 뉴스에 등장하는 사람
    - 위치(LOC): 국가·도시·지역
    - 동사(VERB): 산업 동인 ("급증", "합병", "규제")

를 추출하고 빈도 기반 순위를 산출한다.

설계 원칙:
    - 별도 NER 모델 없이 kiwipiepy POS 태그 + 휴리스틱 규칙으로 분류
    - NNP(고유명사) → 문맥 규칙으로 ORG / PERSON / LOC 분류
    - VV(동사) + NNG+XSV(복합동사) → 산업 동인 동사 추출
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from app.analysis.text_cleaner import TextCleaner

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 분류 규칙 (휴리스틱)
# ---------------------------------------------------------------------------

# ORG: 이 접미어로 끝나는 NNP → 조직으로 분류
_ORG_SUFFIXES = frozenset([
    "전자", "자동차", "반도체", "은행", "증권", "보험", "제약", "화학", "건설",
    "물산", "그룹", "공사", "협회", "위원회", "연구원", "연구소", "대학교", "대학",
    "부", "청", "원", "처", "사", "사(社)", "공단", "재단", "센터",
])

# LOC: 알려진 지명 + 지명 접미어
_LOC_SUFFIXES = frozenset(["국", "시", "도", "구", "군", "읍", "면", "로", "대로"])
_KNOWN_LOCATIONS = frozenset([
    "미국", "중국", "일본", "한국", "유럽", "독일", "프랑스", "영국", "러시아",
    "인도", "호주", "캐나다", "브라질", "멕시코", "태국", "베트남", "인도네시아",
    "서울", "부산", "인천", "대구", "광주", "대전", "울산", "수원", "성남",
    "뉴욕", "워싱턴", "베이징", "상하이", "도쿄", "오사카", "런던", "파리",
    "홍콩", "싱가포르", "두바이", "실리콘밸리", "월스트리트",
])

# PERSON: 이 호칭이 바로 뒤에 오는 NNP → 인물로 분류
_PERSON_TITLES = frozenset([
    "대표", "회장", "부회장", "사장", "부사장", "전무", "상무", "이사",
    "장관", "차관", "장", "청장", "원장", "총장", "이사장",
    "의원", "대통령", "총리", "지사", "시장", "구청장",
    "교수", "박사", "연구원", "연구위원",
    "대표이사", "최고경영자", "CEO", "CFO", "CTO", "COO",
])

# 동사 불용어 (너무 일반적인 동작 동사)
_VERB_STOPWORDS = frozenset([
    "하", "되", "있", "없", "이", "그", "가", "오", "보", "말",
    "받", "주", "두", "나", "들", "올", "한", "못", "안", "잡",
])


# ---------------------------------------------------------------------------
# 데이터 모델
# ---------------------------------------------------------------------------

@dataclass
class EntityFreq:
    """추출된 개체명 + 빈도."""
    term: str
    count: int
    entity_type: str   # 'ORG' | 'PERSON' | 'LOC' | 'MISC'


@dataclass
class VerbFreq:
    """추출된 동사(산업 동인) + 빈도."""
    term: str       # 동사 기본형 (예: "급증하다", "합병하다")
    count: int


@dataclass
class NerReport:
    """NER + POS 분석 결과."""
    total_articles: int
    organizations: list[EntityFreq] = field(default_factory=list)   # ORG top-N
    persons: list[EntityFreq] = field(default_factory=list)          # PERSON top-N
    locations: list[EntityFreq] = field(default_factory=list)        # LOC top-N
    misc_entities: list[EntityFreq] = field(default_factory=list)    # 미분류 NNP
    top_verbs: list[VerbFreq] = field(default_factory=list)          # VERB top-N
    # 카테고리별 보고서 (analyze_by_category 전용)
    by_category: dict[str, "NerReport"] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# NerExtractor
# ---------------------------------------------------------------------------

class NerExtractor:
    """
    kiwipiepy POS 태그 + 휴리스틱 규칙 기반 NER.

    Parameters
    ----------
    top_n : int
        각 카테고리(ORG, PERSON, LOC, VERB)별 반환할 상위 개체 수.
    min_count : int
        최소 등장 횟수. 이 미만이면 결과에서 제외.
    """

    def __init__(self, top_n: int = 50, min_count: int = 3):
        self.top_n = top_n
        self.min_count = min_count
        self._cleaner = TextCleaner()
        self._kiwi = None

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def analyze(self, articles) -> NerReport:
        """
        기사 전체 대상 NER + POS 분석.

        articles: list[NewsArticle] 또는 [(id, body), ...] 형태.
        """
        texts = self._extract_texts(articles)
        if not texts:
            return NerReport(total_articles=0)

        tokens_per_doc = self._tokenize_batch(texts)
        return self._build_report(len(texts), tokens_per_doc)

    def analyze_by_category(self, articles) -> NerReport:
        """카테고리(category_l2)별로 분리해 분석."""
        cat_texts: dict[str, list[str]] = {}
        for article in articles:
            if hasattr(article, "body"):
                body = article.body or ""
                cat = article.category_l2 or "미분류"
            elif len(article) >= 3:
                body = article[1] or ""
                cat = article[2] or "미분류"
            else:
                body = article[1] or ""
                cat = "미분류"
            cat_texts.setdefault(cat, []).append(body)

        total = sum(len(v) for v in cat_texts.values())
        report = NerReport(total_articles=total)

        for cat, texts in cat_texts.items():
            tokens_per_doc = self._tokenize_batch(texts)
            report.by_category[cat] = self._build_report(len(texts), tokens_per_doc)
            logger.info("카테고리 '%s' 완료: ORG=%d PERSON=%d LOC=%d VERB=%d",
                        cat,
                        len(report.by_category[cat].organizations),
                        len(report.by_category[cat].persons),
                        len(report.by_category[cat].locations),
                        len(report.by_category[cat].top_verbs))

        return report

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    @property
    def kiwi(self):
        if self._kiwi is None:
            from kiwipiepy import Kiwi
            logger.info("Kiwi 모델 로딩 중...")
            self._kiwi = Kiwi()
            logger.info("Kiwi 로딩 완료")
        return self._kiwi

    def _extract_texts(self, articles) -> list[str]:
        texts = []
        for a in articles:
            texts.append(a.body if hasattr(a, "body") else a[1] or "")
        return texts

    def _tokenize_batch(self, texts: list[str]) -> list[list]:
        """텍스트 목록 → 정제 → 형태소 분석. doc별 token list 반환."""
        cleaned = self._cleaner.clean_batch(texts)
        placeholders = [t if (t and t.strip()) else " " for t in cleaned]
        return self.kiwi.tokenize(placeholders)

    def _build_report(self, total: int, tokens_per_doc: list[list]) -> NerReport:
        org_counter: Counter = Counter()
        person_counter: Counter = Counter()
        loc_counter: Counter = Counter()
        misc_counter: Counter = Counter()
        verb_counter: Counter = Counter()

        for tokens in tokens_per_doc:
            self._extract_entities(tokens, org_counter, person_counter, loc_counter, misc_counter)
            self._extract_verbs(tokens, verb_counter)

        def to_entity_list(counter: Counter, etype: str) -> list[EntityFreq]:
            return [
                EntityFreq(term=term, count=cnt, entity_type=etype)
                for term, cnt in counter.most_common(self.top_n)
                if cnt >= self.min_count
            ]

        return NerReport(
            total_articles=total,
            organizations=to_entity_list(org_counter, "ORG"),
            persons=to_entity_list(person_counter, "PERSON"),
            locations=to_entity_list(loc_counter, "LOC"),
            misc_entities=to_entity_list(misc_counter, "MISC"),
            top_verbs=[
                VerbFreq(term=term, count=cnt)
                for term, cnt in verb_counter.most_common(self.top_n)
                if cnt >= self.min_count
            ],
        )

    def _extract_entities(
        self,
        tokens: list,
        org: Counter, person: Counter, loc: Counter, misc: Counter,
    ) -> None:
        """
        NNP(고유명사) 토큰을 ORG / PERSON / LOC / MISC로 분류.

        분류 우선순위:
            1. 알려진 지명 → LOC
            2. 지명 접미어 → LOC
            3. 바로 뒤 토큰이 인물 호칭 → PERSON
            4. ORG 접미어 → ORG
            5. 나머지 NNP → MISC
        """
        toks = list(tokens)
        for i, tok in enumerate(toks):
            if tok.tag != "NNP" or len(tok.form) < 2:
                continue
            form = tok.form

            # 1. 알려진 지명
            if form in _KNOWN_LOCATIONS:
                loc[form] += 1
                continue

            # 2. 지명 접미어
            if any(form.endswith(s) for s in _LOC_SUFFIXES):
                loc[form] += 1
                continue

            # 3. 바로 뒤 토큰이 인물 호칭 (NNG 또는 NNP)
            if i + 1 < len(toks) and toks[i + 1].form in _PERSON_TITLES:
                person[form] += 1
                continue

            # 4. ORG 접미어
            if any(form.endswith(s) for s in _ORG_SUFFIXES):
                org[form] += 1
                continue

            # 5. 미분류 NNP
            misc[form] += 1

    def _extract_verbs(self, tokens: list, verb_counter: Counter) -> None:
        """
        동사 추출:
            - VV 태그 (순수 동사)
            - NNG/NNP + XSV 패턴 (복합동사: "급증"+"하다" → "급증하다")
        """
        toks = list(tokens)
        for i, tok in enumerate(toks):
            # 순수 동사 (VV): 2글자 이상, 불용어 제외
            if tok.tag == "VV" and len(tok.form) >= 2 and tok.form not in _VERB_STOPWORDS:
                verb_counter[tok.form + "다"] += 1

            # 복합동사: 명사 + 하(XSV) → "발표하다", "급증하다"
            elif (tok.tag == "XSV" and tok.form == "하"
                  and i > 0 and toks[i - 1].tag in ("NNG", "NNP")
                  and len(toks[i - 1].form) >= 2
                  and toks[i - 1].form not in _VERB_STOPWORDS):
                verb_counter[toks[i - 1].form + "하다"] += 1
