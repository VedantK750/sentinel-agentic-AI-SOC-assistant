def reciprocal_rank_fusion(ranked_lists, k=60, limit=10):
    """Fuse multiple named ranked result lists into one ranking by rank position, not raw score.

    `ranked_lists` is a dict mapping a retriever name (e.g. "bm25", "vector") to its
    results — a sequence of dicts with an "id" key, already sorted best-first by that
    retriever. A doc's fused score is the sum of 1/(k + rank) across every list it
    appears in (rank is 1-indexed), so a document ranked highly by multiple retrievers
    rises even if their raw scores are on incomparable scales.

    Each result carries a "ranks" dict recording which retriever(s) found the doc and
    at what rank (e.g. {"bm25": 2, "vector": 7}), so callers can see whether a result
    came from lexical match, semantic match, or both — retrievers that didn't return
    the doc are simply absent from that dict.
    """
    scores = {}
    docs = {}
    ranks = {}
    for name, ranked in ranked_lists.items():
        for rank, doc in enumerate(ranked, start=1):
            doc_id = doc["id"]
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
            docs.setdefault(doc_id, doc)
            ranks.setdefault(doc_id, {})[name] = rank

    fused = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:limit]
    return [{**docs[doc_id], "rrf_score": score, "ranks": ranks[doc_id]} for doc_id, score in fused]
