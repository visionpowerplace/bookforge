"""docx -> Book model.

Structure detection (the part that makes formatting "automatic"):
  * Heading 1            -> chapter / front-matter / closing section (by title)
  * 'Your ... Action Step' (any style) -> ActionStep module
  * Quote / Intense Quote style, or a standalone all-bold short line -> PullQuote
  * List paragraphs / numbered paragraphs -> ListBlock
  * everything else      -> Para (inline italic/bold preserved)

In the hosted product, an LLM pass refines the ambiguous calls (which bold line is
really a pull-quote, where an exercise begins). The heuristics below already handle
clean manuscripts and the supplied sample.
"""
import html
import re
from docx import Document

from .model import (Book, BookMeta, Chapter, FrontMatterPiece,
                    Para, PullQuote, ListBlock, ActionStep)

FRONT_HINTS = ("before you begin", "introduction", "preface", "foreword",
               "how to use", "author's note")
CLOSING_HINTS = ("final word", "conclusion", "afterword", "closing", "epilogue")


def _runs_to_html(p) -> str:
    out = []
    for r in p.runs:
        t = html.escape(r.text)
        if not t:
            continue
        if r.italic:
            t = f"<em>{t}</em>"
        if r.bold:
            t = f"<strong>{t}</strong>"
        out.append(t)
    return "".join(out).strip()


def _is_heading1(p) -> bool:
    s = (p.style.name or "").lower()
    return s in ("heading 1", "title") or s.startswith("heading 1")


def _is_listish(p) -> bool:
    s = (p.style.name or "").lower()
    if "list" in s:
        return True
    # numbering present on the paragraph
    return p._p.find(".//{http://schemas.openxmlformats.org/wordprocessingml/2006/main}numPr") is not None


def _is_ordered(p) -> bool:
    return "number" in (p.style.name or "").lower()


def _is_quote_style(p) -> bool:
    return "quote" in (p.style.name or "").lower()


def _all_bold(p) -> bool:
    runs = [r for r in p.runs if r.text.strip()]
    return bool(runs) and all(r.bold for r in runs)


def _classify_section(title: str):
    t = title.lower()
    if any(h in t for h in CLOSING_HINTS):
        return "closing"
    if any(h in t for h in FRONT_HINTS):
        return "front"
    return "chapter"


def parse_docx(path: str, meta: BookMeta) -> Book:
    doc = Document(path)
    book = Book(meta=meta)

    # collect (kind, title, paragraphs) sections split on Heading 1
    sections = []
    current = {"title": None, "paras": []}
    for p in doc.paragraphs:
        text = p.text.strip()
        if _is_heading1(p) and text:
            if current["title"] is not None or current["paras"]:
                sections.append(current)
            current = {"title": text, "paras": []}
        else:
            if text == "" and not current["paras"]:
                continue
            current["paras"].append(p)
    if current["title"] is not None or current["paras"]:
        sections.append(current)

    chap_no = 0
    for sec in sections:
        title = sec["title"] or ""
        kind = _classify_section(title) if title else "chapter"
        blocks = _blocks_from_paras(sec["paras"])

        if not title:                       # stray leading content -> ignore
            continue
        if kind == "front":
            book.front_matter.append(FrontMatterPiece(title=title, blocks=blocks))
        elif kind == "closing":
            book.closing = FrontMatterPiece(title=title, blocks=blocks)
        else:
            chap_no += 1
            book.chapters.append(Chapter(number=chap_no, title=title, blocks=blocks))
    return book


def _blocks_from_paras(paras):
    blocks = []
    list_buf, list_ordered = [], False
    in_action, action = False, None

    def flush_list(target):
        nonlocal list_buf
        if list_buf:
            target.append(ListBlock(items=list_buf[:], ordered=list_ordered))
            list_buf = []

    for p in paras:
        text = p.text.strip()
        if not text:
            continue
        # drop boilerplate footers the layout regenerates itself
        if re.fullmatch(r"(chapter\s+\d+|\d+|[ivxl]+)", text.lower()):
            continue
        if re.fullmatch(r"chapter\s*0?\d+", text.lower()):
            continue

        target = action.blocks if in_action else blocks

        # action-step module trigger
        if "action step" in text.lower() and len(text) < 60:
            flush_list(target)
            if in_action:
                blocks.append(action)
            action = ActionStep(title=text)
            in_action = True
            continue

        if _is_listish(p):
            list_ordered = _is_ordered(p)
            list_buf.append(_runs_to_html(p) or html.escape(text))
            continue
        else:
            flush_list(target)

        if _is_quote_style(p) or (_all_bold(p) and len(text) < 240):
            target.append(PullQuote(text=text))
        else:
            target.append(Para(html=_runs_to_html(p) or html.escape(text)))

    # flush tail
    if in_action:
        flush_list(action.blocks)
        blocks.append(action)
    else:
        flush_list(blocks)
    return blocks
