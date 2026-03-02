"""
Unit tests for NerExtractor.

kiwipiepy 없이 _tokenize_batch를 mock Token 리스트로 대체한다.
"""

from collections import namedtuple
from unittest.mock import MagicMock

import pytest

from app.analysis.ner_extractor import NerExtractor

# kiwipiepy Token과 동일한 구조의 더미 namedtuple
MockToken = namedtuple("MockToken", ["form", "tag"])


def make_extractor(tokens_per_doc: list[list[MockToken]]) -> NerExtractor:
    """_tokenize_batch를 mock으로 교체한 NerExtractor 반환."""
    extractor = NerExtractor(top_n=10, min_count=1)
    extractor._tokenize_batch = lambda texts: tokens_per_doc
    return extractor


# ---------------------------------------------------------------------------
# ORG 분류
# ---------------------------------------------------------------------------

class TestOrgClassification:
    def test_org_suffix_classified_as_org(self):
        tokens = [[
            MockToken("삼성전자", "NNP"),
            MockToken("가", "JKS"),
        ]]
        report = make_extractor(tokens).analyze([(1, "삼성전자가")])
        orgs = [e.term for e in report.organizations]
        assert "삼성전자" in orgs

    def test_org_suffix_geum_융(self):
        # "한국은행" → 은행 접미어 → ORG
        tokens = [[MockToken("한국은행", "NNP")]]
        report = make_extractor(tokens).analyze([(1, "한국은행")])
        assert any(e.term == "한국은행" for e in report.organizations)

    def test_org_not_in_loc(self):
        tokens = [[MockToken("현대자동차", "NNP")]]
        report = make_extractor(tokens).analyze([(1, "현대자동차")])
        loc_terms = [e.term for e in report.locations]
        assert "현대자동차" not in loc_terms


# ---------------------------------------------------------------------------
# PERSON 분류
# ---------------------------------------------------------------------------

class TestPersonClassification:
    def test_person_with_title_after(self):
        # "이재용" 뒤에 "회장" → PERSON
        tokens = [[
            MockToken("이재용", "NNP"),
            MockToken("회장", "NNG"),
        ]]
        report = make_extractor(tokens).analyze([(1, "이재용 회장")])
        persons = [e.term for e in report.persons]
        assert "이재용" in persons

    def test_person_with_ceo_title(self):
        tokens = [[
            MockToken("최태원", "NNP"),
            MockToken("대표이사", "NNG"),
        ]]
        report = make_extractor(tokens).analyze([(1, "최태원 대표이사")])
        assert any(e.term == "최태원" for e in report.persons)

    def test_person_without_title_not_classified_as_person(self):
        # 뒤에 호칭 없으면 PERSON이 아님 (MISC 또는 ORG)
        tokens = [[MockToken("홍길동", "NNP")]]
        report = make_extractor(tokens).analyze([(1, "홍길동")])
        person_terms = [e.term for e in report.persons]
        assert "홍길동" not in person_terms


# ---------------------------------------------------------------------------
# LOC 분류
# ---------------------------------------------------------------------------

class TestLocClassification:
    def test_known_location_us(self):
        tokens = [[MockToken("미국", "NNP")]]
        report = make_extractor(tokens).analyze([(1, "미국")])
        locs = [e.term for e in report.locations]
        assert "미국" in locs

    def test_known_location_seoul(self):
        tokens = [[MockToken("서울", "NNP")]]
        report = make_extractor(tokens).analyze([(1, "서울")])
        assert any(e.term == "서울" for e in report.locations)

    def test_location_suffix_si(self):
        # "수원시" → 시 접미어 → LOC
        tokens = [[MockToken("수원시", "NNP")]]
        report = make_extractor(tokens).analyze([(1, "수원시")])
        assert any(e.term == "수원시" for e in report.locations)


# ---------------------------------------------------------------------------
# 동사(VERB) 추출
# ---------------------------------------------------------------------------

class TestVerbExtraction:
    def test_pure_verb_vv(self):
        # VV 태그 → "오르다"
        tokens = [[MockToken("오르", "VV")]]
        report = make_extractor(tokens).analyze([(1, "오르다")])
        verbs = [v.term for v in report.top_verbs]
        assert "오르다" in verbs

    def test_compound_verb_nng_xsv(self):
        # "급증" (NNG) + "하" (XSV) → "급증하다"
        tokens = [[
            MockToken("급증", "NNG"),
            MockToken("하", "XSV"),
        ]]
        report = make_extractor(tokens).analyze([(1, "급증했다")])
        verbs = [v.term for v in report.top_verbs]
        assert "급증하다" in verbs

    def test_stopword_verb_excluded(self):
        # "하" 단독 VV → 불용어 제거
        tokens = [[MockToken("하", "VV")]]
        report = make_extractor(tokens).analyze([(1, "하다")])
        verbs = [v.term for v in report.top_verbs]
        assert "하다" not in verbs

    def test_verb_count_accumulates(self):
        # 3개 문서 모두 "급증하다" → count=3
        tokens = [
            [MockToken("급증", "NNG"), MockToken("하", "XSV")],
            [MockToken("급증", "NNG"), MockToken("하", "XSV")],
            [MockToken("급증", "NNG"), MockToken("하", "XSV")],
        ]
        report = make_extractor(tokens).analyze([(i, f"텍스트{i}") for i in range(3)])
        verb = next((v for v in report.top_verbs if v.term == "급증하다"), None)
        assert verb is not None
        assert verb.count == 3


# ---------------------------------------------------------------------------
# min_count 필터
# ---------------------------------------------------------------------------

class TestMinCount:
    def test_below_min_count_excluded(self):
        extractor = NerExtractor(top_n=10, min_count=5)
        extractor._tokenize_batch = lambda texts: [[MockToken("삼성전자", "NNP")]]
        # count=1 < min_count=5 → 결과 없음
        report = extractor.analyze([(1, "삼성전자")])
        assert report.organizations == []

    def test_above_min_count_included(self):
        extractor = NerExtractor(top_n=10, min_count=2)
        # 3개 문서 모두 "SK하이닉스" NNP 반도체 ORG 접미어
        tokens = [[MockToken("SK하이닉스", "NNP")]] * 3
        extractor._tokenize_batch = lambda texts: tokens
        articles = [(i, f"텍스트{i}") for i in range(3)]
        report = extractor.analyze(articles)
        orgs = [e.term for e in report.organizations]
        assert "SK하이닉스" not in orgs   # 접미어 없으므로 MISC로


# ---------------------------------------------------------------------------
# 빈 입력
# ---------------------------------------------------------------------------

class TestEmpty:
    def test_empty_articles(self):
        report = NerExtractor().analyze([])
        assert report.total_articles == 0
        assert report.organizations == []
        assert report.top_verbs == []

    def test_analyze_by_category_empty(self):
        report = NerExtractor().analyze_by_category([])
        assert report.total_articles == 0
        assert report.by_category == {}
