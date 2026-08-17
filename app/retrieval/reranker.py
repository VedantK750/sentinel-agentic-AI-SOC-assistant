from sentence_transformers import CrossEncoder

from .documents import DOCS_PATH, load_content_by_id

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class CrossEncoderReranker:
    def __init__(self, model_name=MODEL_NAME, docs_path=DOCS_PATH):
        self.model = CrossEncoder(model_name)
        self.content_by_id = load_content_by_id(docs_path)

    def rerank(self, query, candidates, limit=10):
        """Re-score `candidates` (ranked dicts with a "document_id"/"title" key, e.g.
        RRF output) against the full query+document text with a cross-encoder, and
        return the top `limit` re-sorted by that score. Each result keeps its
        `initial_rank` (position coming in) alongside the new `reranker_score` and
        `final_rank`, so callers can see how much reranking actually moved things.
        """
        pairs = [
            (query, f"{c['title']}. {self.content_by_id.get(c['document_id'], '')}")
            for c in candidates
        ]
        scores = self.model.predict(pairs)
        scored = [
            {**c, "initial_rank": i + 1, "reranker_score": float(score)}
            for i, (c, score) in enumerate(zip(candidates, scores))
        ]
        scored.sort(key=lambda r: r["reranker_score"], reverse=True)
        for final_rank, r in enumerate(scored, start=1):
            r["final_rank"] = final_rank
        return scored[:limit]


def main():
    from .bm25_retriever import BM25Retriever
    from .fusion import reciprocal_rank_fusion
    from .vector_retriever import VectorRetriever

    bm25 = BM25Retriever()
    vector = VectorRetriever()
    reranker = CrossEncoderReranker()

    queries = ["T1059", "dump passwords from memory", "detect mimikatz credential dumping"]
    for query in queries:
        rrf_results = reciprocal_rank_fusion(
            {"bm25": bm25.search(query, limit=50), "vector": vector.search(query, limit=50)},
            limit=20,
        )
        reranked = reranker.rerank(query, rrf_results, limit=5)
        print(f"\nquery: {query!r}")
        for r in reranked:
            moved = r["initial_rank"] - r["final_rank"]
            print(
                f"  final#{r['final_rank']}  (was RRF#{r['initial_rank']}, {moved:+d})"
                f"  score={r['reranker_score']:.3f}  {r['document_id']}  {r['title']}"
            )


if __name__ == "__main__":
    main()
