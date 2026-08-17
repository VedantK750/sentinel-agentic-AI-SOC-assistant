import re

from .documents import DOCS_PATH, load_documents

# A registry of known-item identifier patterns, not hardcoded logic per ID type --
# extensible to IOC-style identifiers (IPs, hashes) once that data exists (PLAN
# §4.4). Each entry says "if the query contains something matching `pattern`,
# normalize it and look it up against `metadata_field` on documents in the corpus."
ID_PATTERNS = [
    {
        "name": "attack_technique_id",
        "pattern": re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE),
        "metadata_field": "technique_id",
        "normalize": str.upper,
    },
    {
        "name": "sigma_rule_id",
        "pattern": re.compile(
            r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
        ),
        "metadata_field": "rule_id",
        "normalize": str.lower,
    },
]


class ExactMatchBooster:
    """Detects known-item identifiers (ATT&CK technique IDs, Sigma rule UUIDs, ...)
    in a query and, if the corpus has a document with that exact ID, guarantees it
    ranks first in the final result list.

    Why this exists rather than tuning RRF: reciprocal_rank_fusion only sees rank
    position, never raw score, so it can't distinguish "BM25 rank #1 because this is
    a near-unique exact token match" from "BM25 rank #1 because it happened to edge
    out rank #2 by a hair." An exact identifier match is about as unambiguous as
    retrieval evidence gets -- this makes that certainty explicit instead of hoping
    fusion/rerank parameters happen to preserve it. See DECISIONS.md.

    Deliberately a separate, explicit stage (like reranking) rather than folded into
    HybridSearcher -- so BM25/RRF/RRF+rerank keep meaning exactly what the Phase 4
    eval already measured them to mean, and this stage's own effect can be measured
    on its own.
    """

    def __init__(self, docs_path=DOCS_PATH, patterns=None):
        self.patterns = patterns if patterns is not None else ID_PATTERNS
        documents = load_documents(docs_path)
        # {metadata_field: {normalized_id_value: document}}
        self._index = {}
        for spec in self.patterns:
            field = spec["metadata_field"]
            lookup = {}
            for doc in documents:
                value = doc.get("metadata", {}).get(field)
                if value:
                    lookup[spec["normalize"](value)] = doc
            self._index[field] = lookup

    def detect(self, query):
        """Return exactly-matching documents (as result-shaped dicts) for any known
        identifiers found in `query`, in the order they appear in the query, with
        duplicates removed.
        """
        hits = []
        seen_ids = set()
        for spec in self.patterns:
            lookup = self._index[spec["metadata_field"]]
            for match in spec["pattern"].finditer(query):
                value = spec["normalize"](match.group(0))
                doc = lookup.get(value)
                if doc is None or doc["document_id"] in seen_ids:
                    continue
                seen_ids.add(doc["document_id"])
                hits.append(
                    {
                        "document_id": doc["document_id"],
                        "title": doc["title"],
                        "doc_type": doc["doc_type"],
                        "source": doc["source"]["name"],
                        "exact_match_field": spec["metadata_field"],
                        "exact_match_value": value,
                    }
                )
        return hits

    def boost(self, query, results, limit=None):
        """Re-order `results` (dicts with a "document_id" key, e.g. RRF or
        RRF+rerank output) so any exact identifier match detected in `query` is
        pinned to the front, followed by the rest of `results` with matches
        deduplicated out. A detected exact match is injected even if it wasn't in
        `results` at all -- it's correct by construction, not just highly ranked.
        """
        exact_hits = self.detect(query)
        if not exact_hits:
            return results[:limit] if limit is not None else results

        exact_ids = {hit["document_id"] for hit in exact_hits}
        boosted = [{**hit, "exact_match": True} for hit in exact_hits]
        boosted += [r for r in results if r["document_id"] not in exact_ids]
        return boosted[:limit] if limit is not None else boosted


def main():
    booster = ExactMatchBooster()
    for query in ["What is T1059?", "T1003.001 and T1003.006", "just a normal question", "0022869c-49f7-4ff2-ba03-85ac42ddac58"]:
        hits = booster.detect(query)
        print(f"{query!r:55} -> {[h['document_id'] for h in hits]}")


if __name__ == "__main__":
    main()
