"""Renders a verified answer (claims + retrieved-doc metadata) into a single
flowing, citation-annotated answer instead of a raw claim list -- presentation
only, no effect on what was verified. This is the shape an API/frontend would
actually want: `text` with inline [n] markers plus a `references` list to
render as a sources panel, same pattern as Perplexity/Bing-style AI answers.

Numbering is assigned in first-citation order and is per DOCUMENT, not per
claim -- a document cited by five different claims still gets one marker,
reused each time it's cited again.
"""


def _source_label(source):
    """`source` varies by which retrieval stage produced the result: a
    {name, url} dict (BM25/vector retrievers, straight from the document
    schema) or a bare name string (ExactMatchBooster builds its own entries
    with just doc["source"]["name"]). Handle both rather than assuming one.
    """
    if isinstance(source, dict):
        return source.get("name", ""), source.get("url")
    return source or "", None


def render_answer(claims, retrieved_docs):
    """claims: verified claims [{"text", "cited_document_ids"}] (pipeline output).
    retrieved_docs: the orchestrator's "retrieved" list, used to look up
    title/source for any document a claim actually cited.

    Returns {"text": "...", "references": [{"marker", "document_id", "title",
    "source", "url"}, ...]}. `text` is empty and `references` is [] when
    `claims` is empty (insufficient evidence) -- caller decides how to display that.
    """
    doc_lookup = {d["document_id"]: d for d in retrieved_docs}

    marker_by_doc = {}
    references = []
    sentences = []

    for claim in claims:
        markers = []
        for doc_id in claim["cited_document_ids"]:
            if doc_id not in marker_by_doc:
                marker_by_doc[doc_id] = len(references) + 1
                doc = doc_lookup.get(doc_id, {})
                name, url = _source_label(doc.get("source"))
                references.append({
                    "marker": marker_by_doc[doc_id],
                    "document_id": doc_id,
                    "title": doc.get("title", doc_id),
                    "source": name,
                    "url": url,
                })
            markers.append(marker_by_doc[doc_id])

        text = claim["text"].rstrip()
        if text and not text.endswith((".", "!", "?")):
            text += "."
        marker_text = "".join(f"[{m}]" for m in markers)
        sentences.append(f"{text} {marker_text}".rstrip() if markers else text)

    return {"text": " ".join(s for s in sentences if s), "references": references}
