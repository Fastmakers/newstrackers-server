"""Lazy exports for the services package.

Avoid eager importing optional AI dependencies at package import time.
"""

from __future__ import annotations

from importlib import import_module

_EXPORTS = {
    "LLMClient": ("app.services.llm_client", "LLMClient"),
    "LLMService": ("app.services.llm_service", "LLMService"),
    "NewsService": ("app.services.news_service", "NewsService"),
    "EmbeddingService": ("app.services.embedding_service", "EmbeddingService"),
    "ResumeAnalyzer": ("app.services.resume_analyzer", "ResumeAnalyzer"),
    "ReportGenerator": ("app.services.report_generator", "ReportGenerator"),
    "ReportPipeline": ("app.services.report_pipeline", "ReportPipeline"),
    "ReportInput": ("app.services.report_pipeline", "ReportInput"),
    "FakeResumeAnalyzer": ("app.services.fake_pipeline", "FakeResumeAnalyzer"),
    "FakeNewsService": ("app.services.fake_pipeline", "FakeNewsService"),
    "FakeReportGenerator": ("app.services.fake_pipeline", "FakeReportGenerator"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
