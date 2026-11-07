"""resume_review 图（SPEC 4.2）：可解析度（程序）、内容品质（LLM）、关键词（LLM + 程序）并行，最后合并。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from app.llm.base import LLMError, LLMProvider
from app.resume_review.content import review_content, review_keywords
from app.resume_review.extract import LayoutInfo
from app.resume_review.parse_checks import run_parse_checks
from app.schemas.resume import Finding, ParsedResume


class ReviewState(TypedDict, total=False):
    raw_text: str
    parsed: ParsedResume
    layout: LayoutInfo
    target_role: str | None
    parse_score: int
    parse_findings: list[Finding]
    content_score: int
    content_findings: list[Finding]
    keyword_score: int | None
    keyword_findings: list[Finding]
    findings: list[Finding]


@dataclass
class ReviewOutput:
    parse_score: int
    content_score: int
    keyword_score: int | None
    findings: list[Finding]


def build_graph(content_provider: LLMProvider):
    def parse_check(state: ReviewState) -> ReviewState:
        score, findings = run_parse_checks(state["raw_text"], state["layout"])
        return {"parse_score": score, "parse_findings": findings}

    def content(state: ReviewState) -> ReviewState:
        score, findings = review_content(content_provider, state["parsed"], state["layout"].page_count)
        return {"content_score": score, "content_findings": findings}

    def keywords(state: ReviewState) -> ReviewState:
        role = state.get("target_role")
        if not role:
            return {
                "keyword_score": None,
                "keyword_findings": [
                    Finding(
                        category="keyword",
                        check="role_keywords",
                        status="warn",
                        message="没有指定目标职位，未检查关键词覆盖。请在求职需求填写目标职位，或评分时指定。",
                    )
                ],
            }
        try:
            score, findings = review_keywords(content_provider, role, state["raw_text"])
        except LLMError as exc:
            return {
                "keyword_score": None,
                "keyword_findings": [
                    Finding(
                        category="keyword",
                        check="role_keywords",
                        status="warn",
                        message=f"关键词检查失败，未计分：{exc}",
                    )
                ],
            }
        return {"keyword_score": score, "keyword_findings": findings}

    def merge(state: ReviewState) -> ReviewState:
        return {"findings": [*state["parse_findings"], *state["content_findings"], *state["keyword_findings"]]}

    g = StateGraph(ReviewState)
    g.add_node("parse_check", parse_check)
    g.add_node("content", content)
    g.add_node("keywords", keywords)
    g.add_node("merge", merge)
    for node in ("parse_check", "content", "keywords"):
        g.add_edge(START, node)
    g.add_edge(["parse_check", "content", "keywords"], "merge")
    g.add_edge("merge", END)
    return g.compile()


def run_review(
    provider: LLMProvider, raw_text: str, parsed: ParsedResume, layout: LayoutInfo, target_role: str | None
) -> ReviewOutput:
    state = build_graph(provider).invoke(
        {"raw_text": raw_text, "parsed": parsed, "layout": layout, "target_role": target_role}
    )
    return ReviewOutput(
        parse_score=state["parse_score"],
        content_score=state["content_score"],
        keyword_score=state.get("keyword_score"),
        findings=state["findings"],
    )
