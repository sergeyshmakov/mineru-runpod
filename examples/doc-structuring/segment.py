"""Assign a flat MinerU block stream to sections, in document reading order.

The core is a single forward walk: each block belongs to the section whose heading most
recently appeared. Because boundaries are only ever set by a real heading, a section can
never steal a neighbour's content (the failure mode of page/position heuristics).

You inject `heading_id(block) -> section_id | None`. That callback is where your
domain lives: match a numbered heading, a styled `text_level` line, a code-caption that
holds a heading, an annex title, etc. Keep it precise — false headings fragment content.
"""

from __future__ import annotations

from typing import Callable

from model import Section


def attach_pages(blocks: list[dict], start_page: int = 0) -> list[dict]:
    """Stamp each block with its absolute source page. MinerU 4 reports `page_idx` as the
    page's 0-based number in the original document, even when a `page_range` parsed only a
    slice, so it is used as is; the slice's `start_page` only stands in for a block that
    has no `page_idx`. Returns the same list."""
    for b in blocks:
        pi = b.get("page_idx")
        b["_abs_page"] = pi if isinstance(pi, int) else start_page
    return blocks


def merge_split_headings(
    blocks: list[dict],
    bare_id: Callable[[str], "str | None"],
    title_like: Callable[[str], bool],
) -> list[dict]:
    """Repair headings a VLM split across two blocks — the number alone in one text block
    ("L.4.8.4.3") and the title in the next ("Blip Fills"). Neither a number-matcher nor a
    title-matcher fires on either half, so the heading is missed and its body bleeds into
    the previous section. Merge such a pair into one "id title" heading block (carrying
    `text_level` so `heading_id` recognises it).

    `bare_id(text) -> id | None`  : the text is ONLY a known section id (else None).
    `title_like(text) -> bool`    : the text reads like a title (short, not a sentence).
    Both are yours to define, since id format and title shape are document-specific.
    """
    out: list[dict] = []
    i, n = 0, len(blocks)
    while i < n:
        b = blocks[i]
        sid = bare_id((b.get("text") or "").strip()) if b.get("type") == "text" else None
        if sid is not None and i + 1 < n:
            nxt = blocks[i + 1]
            ntext = (nxt.get("text") or "").strip()
            if nxt.get("type") == "text" and title_like(ntext):
                out.append({"type": "text", "text": f"{sid} {ntext}",
                            "text_level": 1, "_abs_page": b.get("_abs_page")})
                i += 2
                continue
        out.append(b)
        i += 1
    return out


def segment_stream(
    blocks: list[dict],
    sections_by_id: dict[str, Section],
    heading_id: Callable[[dict], "str | None"],
    is_noise: Callable[[dict], bool] | None = None,
    order: list[str] | None = None,
    boundary: Callable[[dict, "Section | None", Section], bool] | None = None,
) -> set[str]:
    """Fill `section.blocks` for every section that appears in `blocks`.

    Returns the set of section ids whose heading was matched (so you can report
    coverage / find unmatched sections).

    Optional `order` + `boundary` recover sections whose heading the VLM dropped but whose
    start is marked *structurally* (e.g. a metadata table opens each entry). `order` is the
    section ids in document order; `boundary(block, current, next_expected) -> bool` returns
    True when `block` marks the start of `next_expected` (the next not-yet-matched section).
    On True the walk advances to it (synthesising the missing boundary) and the block is
    then assigned to it as content."""
    pos = {sid: i for i, sid in enumerate(order or [])}
    current: Section | None = None
    matched: set[str] = set()
    ep = 0          # index into `order`: the next expected section
    for b in blocks:
        sid = heading_id(b)
        if sid is not None and sid in sections_by_id:
            current = sections_by_id[sid]
            matched.add(sid)
            if sid in pos:
                ep = pos[sid] + 1
            continue          # the heading itself isn't body content (the tree emits its own H1)
        if order and boundary and ep < len(order):
            nxt = sections_by_id.get(order[ep])
            if nxt is not None and nxt.id not in matched and boundary(b, current, nxt):
                current = nxt
                matched.add(nxt.id)
                ep += 1
        if current is None or (is_noise and is_noise(b)):
            continue
        current.blocks.append(b)
    return matched
