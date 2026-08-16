import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.retrieval.bm25_retriever import BM25Retriever  # noqa: E402
from app.retrieval.exact_match import ExactMatchBooster  # noqa: E402
from app.retrieval.fusion import reciprocal_rank_fusion  # noqa: E402
from app.retrieval.reranker import CrossEncoderReranker  # noqa: E402
from app.retrieval.vector_retriever import VectorRetriever  # noqa: E402

DOCS_PATH = ROOT / "data" / "documents.json"

K = 10
RRF_CANDIDATE_LIMIT = 50
RERANK_CANDIDATE_LIMIT = 20
METHODS = ["bm25", "vector", "rrf", "rrf+rerank", "rrf+rerank+boost"]

# A document is judged relevant to a query if its title matches the rule below
# (all `terms` present, and if given, at least one of `any_terms` present) --
# a title-substring heuristic used as a reproducible proxy for ground truth in
# the absence of hand-labeled relevance judgments. See DECISIONS.md.
EVAL_QUERIES = [
    {"query": "T1059", "technique_id_equals": "T1059"},
    # Deliberately the natural-language phrasing of an exact-ID lookup, not the bare
    # ID -- this is the query shape that exposed both the BM25 stopword bug and the
    # RRF-can't-see-confidence limitation that ExactMatchBooster now compensates
    # for. See DECISIONS.md.
    {"query": "What is T1003.001?", "technique_id_equals": "T1003.001"},
    {"query": "credential dumping", "terms": ["credential dump"]},
    {"query": "powershell execution", "terms": ["powershell", "execution"]},
    {"query": "curl file upload", "terms": ["curl", "upload"]},
    {"query": "mimikatz", "terms": ["mimikatz"]},
    {"query": "ransomware", "terms": ["ransomware"]},
    {"query": "phishing", "terms": ["phish"]},
    {"query": "lsass", "terms": ["lsass"]},
    {
        "query": "disable defender",
        "terms": ["defender"],
        "any_terms": ["disable", "tamper", "bypass", "exclu", "remov", "uninstall"],
    },
    {"query": "reverse shell", "terms": ["reverse shell"]},
]


def build_relevance_sets(documents):
    relevance = {}
    for spec in EVAL_QUERIES:
        if "technique_id_equals" in spec:
            relevant = {
                doc["document_id"]
                for doc in documents
                if doc.get("doc_type") == "attack_technique"
                and doc.get("metadata", {}).get("technique_id") == spec["technique_id_equals"]
            }
            relevance[spec["query"]] = relevant
            continue
        relevant = set()
        for doc in documents:
            title = doc.get("title", "").lower()
            if not all(term in title for term in spec["terms"]):
                continue
            if "any_terms" in spec and not any(t in title for t in spec["any_terms"]):
                continue
            relevant.add(doc["document_id"])
        relevance[spec["query"]] = relevant
    return relevance


def hit_at_k(ranked_ids, relevant, k):
    return 1.0 if any(doc_id in relevant for doc_id in ranked_ids[:k]) else 0.0


def recall_at_k(ranked_ids, relevant, k):
    if not relevant:
        return None
    hits = sum(1 for doc_id in ranked_ids[:k] if doc_id in relevant)
    return hits / len(relevant)


def mrr(ranked_ids, relevant):
    for i, doc_id in enumerate(ranked_ids, start=1):
        if doc_id in relevant:
            return 1.0 / i
    return 0.0


def main():
    documents = json.loads(DOCS_PATH.read_text(encoding="utf-8"))
    relevance = build_relevance_sets(documents)

    bm25 = BM25Retriever()
    vector = VectorRetriever()
    reranker = CrossEncoderReranker()
    booster = ExactMatchBooster()

    totals = {m: {"hit": 0.0, "recall": [], "mrr": 0.0} for m in METHODS}

    header = f"{'query':<24}{'method':<14}{'hit@' + str(K):<10}{'recall@' + str(K):<12}{'mrr':<8}"
    print(header)
    print("-" * len(header))

    for spec in EVAL_QUERIES:
        query = spec["query"]
        relevant = relevance[query]
        print(f"# {query}  ({len(relevant)} relevant docs by title rule)")

        bm25_results = bm25.search(query, limit=RRF_CANDIDATE_LIMIT)
        vector_results = vector.search(query, limit=RRF_CANDIDATE_LIMIT)
        rrf_results = reciprocal_rank_fusion(
            {"bm25": bm25_results, "vector": vector_results}, limit=RERANK_CANDIDATE_LIMIT
        )
        reranked_wide = reranker.rerank(query, rrf_results, limit=RERANK_CANDIDATE_LIMIT)
        boosted = booster.boost(query, reranked_wide, limit=K)

        runs = {
            "bm25": [d["document_id"] for d in bm25_results],
            "vector": [d["document_id"] for d in vector_results],
            "rrf": [d["document_id"] for d in rrf_results],
            "rrf+rerank": [d["document_id"] for d in reranked_wide[:K]],
            "rrf+rerank+boost": [d["document_id"] for d in boosted],
        }

        for method in METHODS:
            ranked_ids = runs[method]
            h = hit_at_k(ranked_ids, relevant, K)
            r = recall_at_k(ranked_ids, relevant, K)
            m = mrr(ranked_ids, relevant)
            totals[method]["hit"] += h
            if r is not None:
                totals[method]["recall"].append(r)
            totals[method]["mrr"] += m
            r_str = "n/a" if r is None else f"{r:.2f}"
            print(f"{'':<24}{method:<14}{h:<10.2f}{r_str:<12}{m:<8.2f}")
        print()

    n = len(EVAL_QUERIES)
    print("=== aggregate over all queries ===")
    print(f"{'method':<14}{'hit@' + str(K):<10}{'recall@' + str(K):<12}{'mrr':<8}")
    for method in METHODS:
        avg_hit = totals[method]["hit"] / n
        recalls = totals[method]["recall"]
        avg_recall = sum(recalls) / len(recalls) if recalls else float("nan")
        avg_mrr = totals[method]["mrr"] / n
        print(f"{method:<14}{avg_hit:<10.3f}{avg_recall:<12.3f}{avg_mrr:<8.3f}")


if __name__ == "__main__":
    main()
