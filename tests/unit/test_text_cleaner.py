"""
Unit tests for TextCleaner.
"""

import pytest

from app.analysis.text_cleaner import TextCleaner


@pytest.fixture
def cleaner():
    return TextCleaner()


class TestEmailAndURL:
    def test_removes_email(self, cleaner):
        assert "reporter@mk.co.kr" not in cleaner.clean("홍길동 reporter@mk.co.kr 기사 내용")

    def test_removes_url(self, cleaner):
        assert "https://" not in cleaner.clean("자세한 내용은 https://www.mk.co.kr/news/123 참고")

    def test_keeps_normal_text(self, cleaner):
        text = "삼성전자가 반도체 시장에서 점유율을 확대했다."
        assert cleaner.clean(text) == text


class TestCopyright:
    def test_removes_mkeconomy_copyright(self, cleaner):
        result = cleaner.clean("기사 내용\nⓒ 매일경제 & mk.co.kr, 무단전재 및 재배포 금지")
        assert "ⓒ" not in result
        assert "무단전재" not in result

    def test_removes_redistribution_notice(self, cleaner):
        result = cleaner.clean("기사 본문\n무단 전재 및 재배포 금지")
        assert "무단" not in result

    def test_removes_copyright_variant(self, cleaner):
        result = cleaner.clean("내용\n© 매일경제, 모든 권리 보유")
        assert "©" not in result


class TestPhotoAndAgencyTags:
    def test_removes_photo_tag(self, cleaner):
        result = cleaner.clean("행사 현장 [사진 = 연합뉴스]")
        assert "[사진" not in result

    def test_removes_photo_source_tag(self, cleaner):
        result = cleaner.clean("이미지 [사진출처=게티이미지코리아]")
        assert "[사진출처" not in result

    def test_removes_agency_tag_with_equals(self, cleaner):
        result = cleaner.clean("발표 현장 [AP=연합뉴스]")
        assert "[AP=" not in result

    def test_removes_news_agency_bracket(self, cleaner):
        result = cleaner.clean("현장 [연합뉴스]")
        assert "[연합뉴스]" not in result

    def test_removes_mk_db_tag(self, cleaner):
        result = cleaner.clean("자료 [매경DB]")
        assert "[매경DB]" not in result


class TestByline:
    def test_removes_reporter_byline(self, cleaner):
        result = cleaner.clean("홍길동 기자가 취재했습니다. 홍길동 기자")
        # 바이라인(문장 끝 "홍길동 기자")이 제거되어야 함
        assert "기자" not in result

    def test_removes_correspondent(self, cleaner):
        result = cleaner.clean("뉴욕 = 홍길동 특파원")
        assert "특파원" not in result


class TestWhitespace:
    def test_normalizes_multiple_newlines(self, cleaner):
        result = cleaner.clean("첫 번째 단락\n\n\n\n두 번째 단락")
        assert "\n\n\n" not in result

    def test_normalizes_multiple_spaces(self, cleaner):
        result = cleaner.clean("단어1   단어2    단어3")
        assert "  " not in result

    def test_strips_leading_trailing(self, cleaner):
        result = cleaner.clean("   내용   ")
        assert result == "내용"


class TestCleanBatch:
    def test_batch_returns_same_length(self, cleaner):
        texts = ["기사1 reporter@mk.co.kr", "기사2 [사진=연합뉴스]", "정상 기사"]
        results = cleaner.clean_batch(texts)
        assert len(results) == 3

    def test_batch_empty_list(self, cleaner):
        assert cleaner.clean_batch([]) == []

    def test_empty_string_passthrough(self, cleaner):
        assert cleaner.clean("") == ""
