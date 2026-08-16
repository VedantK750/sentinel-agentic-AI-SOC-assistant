from .bm25_retriever import BM25Retriever
from .fusion import reciprocal_rank_fusion
from .vector_retriever import VectorRetriever

CANDIDATE_LIMIT = 50
RRF_K = 60


class HybridSearcher:
    def __init__(self, k=RRF_K, candidate_limit=CANDIDATE_LIMIT):
        self.bm25 = BM25Retriever()
        self.vector = VectorRetriever()
        self.k = k
        self.candidate_limit = candidate_limit

    def search(self, query, limit=10):
        bm25_results = self.bm25.search(query, limit=self.candidate_limit)
        vector_results = self.vector.search(query, limit=self.candidate_limit)
        return reciprocal_rank_fusion(
            {"bm25": bm25_results, "vector": vector_results}, k=self.k, limit=limit
        )


def main():
    searcher = HybridSearcher()
    queries = [
        "curl file upload",
        "dump passwords from memory",
        "T1059",
        "lateral movement using WMI",
        "detect mimikatz credential dumping",
    ]
    for query in queries:
        results = searcher.search(query, limit=5)
        print(f"\nquery: {query!r}")
        for r in results:
            ranks = " ".join(f"{name}#{rank}" for name, rank in r["ranks"].items())
            print(f"  {r['rrf_score']:.4f}  {r['document_id']}  {r['title']}  ({r['source']})  [{ranks}]")


if __name__ == "__main__":
    main()
