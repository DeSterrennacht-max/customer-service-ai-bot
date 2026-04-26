from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from math import ceil
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.api.app.db.models.entities import FAQEntry, KnowledgeChunk, KnowledgePage
from backend.api.app.services.image_storage_service import normalize_image_assets

MARKDOWN_LINK_PATTERN = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
ENGLISH_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
CJK_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]+")
STOP_TERMS = {"请问", "一下", "一个", "那个", "这个", "我们", "你们"}
MAX_DIRECT_REPLY_LENGTH = 1200


@dataclass(slots=True)
class RetrievedKnowledge:
    text: str
    evidence: list[str]
    source_type: str
    structured: bool = False
    image_assets: list[dict[str, object]] = field(default_factory=list)


@dataclass(slots=True)
class MarkdownSection:
    heading_level: int
    raw: str
    rendered: str
    index: int


def chunk_markdown(body_markdown: str, chunk_size: int = 500) -> list[str]:
    cleaned = "\n".join(line.strip() for line in body_markdown.splitlines() if line.strip())
    if not cleaned:
        return []
    chunk_count = max(1, ceil(len(cleaned) / chunk_size))
    return [cleaned[index * chunk_size : (index + 1) * chunk_size] for index in range(chunk_count)]


def normalize_search_text(text: str) -> str:
    text = MARKDOWN_LINK_PATTERN.sub(lambda match: f"{match.group(1)} {match.group(2)}", text.lower())
    text = re.sub(r"[^\w\u4e00-\u9fff:/.\-\s]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def extract_search_terms(text: str) -> set[str]:
    normalized = normalize_search_text(text)
    if not normalized:
        return set()

    terms = {token for token in ENGLISH_TOKEN_PATTERN.findall(normalized) if len(token) >= 2}
    for run in CJK_TOKEN_PATTERN.findall(normalized):
        if len(run) <= 4:
            terms.add(run)
        else:
            terms.add(run)
            max_size = min(6, len(run))
            for size in range(2, max_size + 1):
                for index in range(len(run) - size + 1):
                    terms.add(run[index : index + size])

    return {term for term in terms if len(term) >= 2 and term not in STOP_TERMS}


def score_text_match(query: str, text: str) -> int:
    query_normalized = normalize_search_text(query)
    text_normalized = normalize_search_text(text)
    if not query_normalized or not text_normalized:
        return 0

    score = 0
    if query_normalized in text_normalized:
        score += 60

    for term in extract_search_terms(query):
        if term in text_normalized:
            score += min(len(term) * 4, 18)

    ratio = SequenceMatcher(None, query_normalized, text_normalized).ratio()
    score += int(ratio * 10)
    return score


def parse_markdown_sections(markdown: str) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    current: list[str] = []
    current_level = 0
    section_index = 0
    for raw_line in markdown.splitlines():
        line = raw_line.rstrip()
        heading_match = re.match(r"^(#{1,6})\s+", line.strip())
        if heading_match and current:
            raw_section = "\n".join(current).strip()
            sections.append(
                MarkdownSection(
                    heading_level=current_level,
                    raw=raw_section,
                    rendered=render_markdown_as_reply(raw_section),
                    index=section_index,
                )
            )
            section_index += 1
            current = [line]
            current_level = len(heading_match.group(1))
        else:
            if heading_match and not current:
                current_level = len(heading_match.group(1))
            current.append(line)
    if current:
        raw_section = "\n".join(current).strip()
        sections.append(
            MarkdownSection(
                heading_level=current_level,
                raw=raw_section,
                rendered=render_markdown_as_reply(raw_section),
                index=section_index,
            )
        )
    return [section for section in sections if section.raw.strip()]


def is_title_only_section(section: str, title: str) -> bool:
    rendered = render_markdown_as_reply(section)
    title_text = render_markdown_as_reply(title)
    if not rendered or not title_text:
        return False
    return normalize_search_text(rendered) == normalize_search_text(title_text)


def collect_child_sections(sections: list[MarkdownSection], parent: MarkdownSection) -> list[MarkdownSection]:
    children: list[MarkdownSection] = []
    for section in sections[parent.index + 1 :]:
        if section.heading_level and section.heading_level <= parent.heading_level:
            break
        if section.heading_level and section.heading_level > parent.heading_level:
            children.append(section)
    return children


def render_markdown_as_reply(markdown: str) -> str:
    rendered_lines: list[str] = []
    for raw_line in markdown.splitlines():
        line = raw_line.strip()
        if not line:
            if rendered_lines and rendered_lines[-1] != "":
                rendered_lines.append("")
            continue

        line = re.sub(r"^#{1,6}\s*", "", line)
        line = MARKDOWN_LINK_PATTERN.sub(lambda match: f"{match.group(1)}：{match.group(2)}", line)
        line = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        line = re.sub(r"__(.*?)__", r"\1", line)
        line = re.sub(r"`([^`]+)`", r"\1", line)
        rendered_lines.append(line)

    return "\n".join(rendered_lines).strip()


def drop_first_heading_line(rendered_section: str) -> str:
    lines = [line for line in rendered_section.splitlines()]
    if len(lines) <= 1:
        return rendered_section
    return "\n".join(lines[1:]).strip()


def select_knowledge_reply(title: str, body_markdown: str, query: str) -> str:
    rendered_body = render_markdown_as_reply(body_markdown)
    sections = parse_markdown_sections(body_markdown)
    if len(sections) <= 1:
        return rendered_body[:MAX_DIRECT_REPLY_LENGTH].strip() if len(rendered_body) > MAX_DIRECT_REPLY_LENGTH else rendered_body

    scored_sections = [
        (score_text_match(query, section.raw), section)
        for section in sections
        if not is_title_only_section(section.raw, title)
    ]
    relevant_sections = [item for item in scored_sections if item[0] > 0]
    if not relevant_sections:
        return rendered_body[:MAX_DIRECT_REPLY_LENGTH].strip() if len(rendered_body) > MAX_DIRECT_REPLY_LENGTH else rendered_body

    relevant_sections.sort(key=lambda item: item[0], reverse=True)
    top_score = relevant_sections[0][0]
    top_section = relevant_sections[0][1]
    if top_score >= 24:
        selected_sections = [section for score, section in relevant_sections if score >= top_score - 3][:2]
    elif top_score >= 12:
        selected_sections = [section for score, section in relevant_sections if score >= top_score - 4][:3]
    else:
        selected_sections = [section for _, section in relevant_sections[:3]]

    attached_child_sections = False
    if "http://" not in top_section.rendered and "https://" not in top_section.rendered:
        child_sections = collect_child_sections(sections, top_section)
        if child_sections:
            if any("http://" in child.rendered or "https://" in child.rendered for child in child_sections):
                selected_sections = [top_section, *child_sections]
                attached_child_sections = True

    deduped_sections: list[MarkdownSection] = []
    seen_indexes: set[int] = set()
    for section in selected_sections:
        if section.index in seen_indexes:
            continue
        seen_indexes.add(section.index)
        deduped_sections.append(section)

    selected_sections = sorted(deduped_sections, key=lambda section: section.index)
    rendered_parts: list[str] = []
    for section in selected_sections:
        section_text = section.rendered
        if attached_child_sections and section.index == top_section.index:
            section_text = drop_first_heading_line(section_text)
        if section_text:
            rendered_parts.append(section_text)

    reply = "\n\n".join(rendered_parts).strip()
    return reply[:MAX_DIRECT_REPLY_LENGTH].strip() if len(reply) > MAX_DIRECT_REPLY_LENGTH else reply


class KnowledgeService:
    def rebuild_chunks(self, db: Session, page: KnowledgePage) -> list[KnowledgeChunk]:
        db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.knowledge_page_id == page.id))
        chunks: list[KnowledgeChunk] = []
        for index, content in enumerate(chunk_markdown(page.body_markdown)):
            chunk = KnowledgeChunk(
                tenant_id=page.tenant_id,
                knowledge_page_id=page.id,
                chunk_index=index,
                content_text=content,
                token_count=max(1, len(content.split())),
                metadata_json={"title": page.title},
            )
            db.add(chunk)
            chunks.append(chunk)
        db.flush()
        return chunks

    def find_faq_answer(self, db: Session, bot_profile_id: UUID, message: str) -> FAQEntry | None:
        candidates = db.scalars(
            select(FAQEntry)
            .where(FAQEntry.bot_profile_id == bot_profile_id, FAQEntry.status == "active")
            .order_by(FAQEntry.priority.asc())
        ).all()
        lowered = message.lower()
        for faq in candidates:
            patterns = faq.question_patterns_json or []
            if any(pattern.lower() in lowered for pattern in patterns):
                return faq
        return None

    def retrieve_faq(self, db: Session, bot_profile_id: UUID, message: str) -> RetrievedKnowledge | None:
        faq = self.find_faq_answer(db, bot_profile_id, message)
        if faq:
            return RetrievedKnowledge(
                text=faq.canonical_answer,
                evidence=[f"faq:{faq.id}"],
                source_type="faq",
                structured=False,
                image_assets=normalize_image_assets(faq.image_assets_json),
            )
        return None

    def retrieve_knowledge_page(self, db: Session, bot_profile_id: UUID, message: str) -> RetrievedKnowledge | None:
        pages = db.scalars(
            select(KnowledgePage).where(KnowledgePage.bot_profile_id == bot_profile_id, KnowledgePage.status == "active")
        ).all()
        best_page: KnowledgePage | None = None
        best_score = 0
        best_chunk_ids: list[str] = []
        for page in pages:
            tags_text = "\n".join(page.tags_json or [])
            page_score = score_text_match(message, page.title) * 4
            page_score += score_text_match(message, tags_text) * 3
            page_score += score_text_match(message, page.body_markdown)
            chunks = db.scalars(select(KnowledgeChunk).where(KnowledgeChunk.knowledge_page_id == page.id)).all()
            chunk_scores: list[tuple[int, KnowledgeChunk]] = []
            for chunk in chunks:
                score = score_text_match(message, chunk.content_text)
                if score > 0:
                    chunk_scores.append((score, chunk))
            chunk_scores.sort(key=lambda item: item[0], reverse=True)
            page_score += sum(score for score, _ in chunk_scores[:2])
            if page_score > best_score:
                best_score = page_score
                best_page = page
                best_chunk_ids = [str(chunk.id) for _, chunk in chunk_scores[:3]]

        if not best_page or best_score <= 0:
            return None

        reply_text = select_knowledge_reply(best_page.title, best_page.body_markdown, message)
        evidence = [f"knowledge_page:{best_page.id}", *[f"chunk:{chunk_id}" for chunk_id in best_chunk_ids]]
        return RetrievedKnowledge(
            text=reply_text,
            evidence=evidence,
            source_type="knowledge_page",
            structured=True,
            image_assets=normalize_image_assets(best_page.image_assets_json),
        )
