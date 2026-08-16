# Decisions

A running log of non-obvious technical decisions: what was chosen, why, and what was ruled out. Newest first.

---

## 2026-08-16 — Hybrid retrieval combined via Reciprocal Rank Fusion (RRF)

**Decision:** Combine BM25 (lexical) and Qdrant (semantic/vector) search results with Reciprocal Rank Fusion, instead of a weighted score blend or a learned re-ranker.

**What RRF does:** each retriever returns its own ranked list for a query. RRF ignores the raw scores entirely and fuses purely on rank position:

```
score(doc) = sum over each retriever's list containing doc of  1 / (k + rank_in_that_list)
```

A doc missing from a list contributes 0 from that list. Docs are then re-sorted by this summed score. See `app/retrieval/fusion.py`.

**Why RRF specifically:**
- BM25 scores (unbounded term-frequency-based) and cosine similarity scores (0–1) live on incompatible scales. Any weighted-sum blend needs per-retriever normalization that has to be re-tuned as the corpus grows — RRF sidesteps this because it never looks at the raw score, only the position.
- The query patterns in this domain are genuinely bimodal: exact lookups ("T1059", "Invoke-Mimikatz") are won by BM25's exact-token matching; paraphrased/conceptual queries ("dump passwords from memory") are won by embeddings. Confirmed empirically — `scripts/index_bm25.py` and `scripts/index_qdrant.py` already surface different top hits for the same test queries. Neither retriever alone is sufficient.
- RRF is parameter-light (one constant, `k`) and needs no training data or labeled relevance judgments, unlike a learned re-ranker — appropriate for a corpus with no click/relevance data yet.
- It's a well-established baseline (Cormack, Clarke & Buettcher, 2009) that reliably beats either single-method retrieval in hybrid search, so it's a strong default before investing in anything fancier.

**Alternatives considered and rejected (for now):**
- *Weighted score fusion* (normalize each retriever's scores, sum with tuned weights) — more tunable in theory, but brittle: BM25 score distributions shift as documents are added/removed, so weights would need periodic recalibration.
- *Cross-encoder re-ranking* on top of a single retriever — more accurate per-query but adds a second model + real latency. Treated as a candidate *future* layer on top of RRF's candidate set, not a replacement for it (see Architecture "Not yet built").
- *Vector-only retrieval* — rejected outright: this corpus is full of exact identifiers (ATT&CK technique IDs, Sigma rule UUIDs, tool/command names) that embeddings routinely under-rank relative to lexical match.

**Parameters chosen:**
- `k = 60` — the constant from the original RRF paper. It dampens how much rank #1 dominates the fused score (without it, rank 1 vs rank 2 would swing the score by 100%; with k=60 the swing is ~1.6%), which matters because BM25's rank-1 result and the vector retriever's rank-1 result don't need to agree for a doc to still surface near the top. Left as the paper default since there's no eval set yet to tune against.
- `candidate_limit = 50` per retriever before fusion — wide enough that a doc which is mediocre-but-present in both lists can out-rank a doc that's #1 in only one list, without pulling in so many candidates that fusion cost balloons.

---

## 2026-08-16 — Retrieval logic lives in `app/`, not `scripts/`

**Decision:** `app/retrieval/` holds `BM25Retriever`, `VectorRetriever`, `HybridSearcher` as classes; `scripts/` stays limited to one-shot ETL (parsing sources, building indices).

**Why:** `scripts/*.py` are run-once-and-exit jobs — parse a source dump, rebuild an index file on disk. Retrieval is different: it's stateful (a loaded BM25 pickle, a loaded sentence-transformer model, an open Qdrant client) and needs to be instantiated once and reused across many queries. That's the shape of the thing a future FastAPI service will hold in memory per-process, not a script. Keeping the split makes the eventual API layer a thin wrapper around `app/retrieval` rather than a rewrite of it.
