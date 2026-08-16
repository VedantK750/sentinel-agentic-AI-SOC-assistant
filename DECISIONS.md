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

## 2026-08-16 — RRF fusion is keyed by retriever name, not positional list order

**Decision:** `reciprocal_rank_fusion` takes a `dict[str, list]` (e.g. `{"bm25": ..., "vector": ...}`) instead of a plain list of ranked lists, and returns a `"ranks"` dict per fused result recording which retriever(s) surfaced that doc and at what rank.

**Why:** PLAN.md §9 explicitly requires the fused result to carry "BM25 rank if present, dense rank if present" — not just the final RRF score. Without this, there's no way to explain *why* a doc ranked where it did, which matters for two concrete downstream needs: the Phase 4 reranker output wants an "initial rank" per candidate, and the Phase 4 eval wants qualitative examples of "BM25 found it, vector didn't" (or vice versa). Naming the lists (rather than relying on positional order — index 0 is always BM25, index 1 is always vector) also means `fusion.py` stays correct if a third retriever is ever added, without silently mislabeling ranks.

**Verified:** querying `"T1059"` now visibly shows `[bm25#1]` with no vector entry for the top result, while the vector retriever's own #1 for that query is `T1065` (a false friend, no `T1059` in it at all) — a real example of BM25 rescuing an exact-ID query that embeddings alone would get wrong.

---

## 2026-08-16 — `.gitignore` excludes all regenerable data, including the 51MB raw MITRE dump

**Decision:** `data/sigma/` (external git clone), `data/documents.json`, `data/bm25_index.pkl`, `data/bm25_meta.json`, and `data/qdrant_db/` are all gitignored as build artifacts reproducible by re-running `scripts/`. `data/enterprise-attack.json` (51MB) is also gitignored, even though nothing currently re-fetches it.

**Why:**
- `data/sigma/` is a full clone of `SigmaHQ/sigma` with its own `.git/` — committing it would create a nested/embedded repo that git treats as a broken submodule reference. `parse_sigma.py`'s `ensure_sigma_rules()` already re-clones it if missing, so there's no reason to track it.
- `documents.json`, the BM25 pickle, and the Qdrant collection are all deterministic outputs of `scripts/*.py` run against the two inputs above — tracking build outputs alongside the inputs that produce them just invites drift (stale index committed, code changed, no way to tell without rebuilding).
- `enterprise-attack.json` is the one exception worth flagging: unlike Sigma, there's currently **no script that fetches it** — it was present in `data/` already. Gitignoring it without a fetch script means a fresh clone of this repo cannot rebuild the corpus from scratch yet. Tracked as an open gap in [PROGRESS.md](PROGRESS.md) Phase 1 rather than solved by committing a 51MB JSON file into git history.

---

## 2026-08-16 — Retrieval logic lives in `app/`, not `scripts/`

**Decision:** `app/retrieval/` holds `BM25Retriever`, `VectorRetriever`, `HybridSearcher` as classes; `scripts/` stays limited to one-shot ETL (parsing sources, building indices).

**Why:** `scripts/*.py` are run-once-and-exit jobs — parse a source dump, rebuild an index file on disk. Retrieval is different: it's stateful (a loaded BM25 pickle, a loaded sentence-transformer model, an open Qdrant client) and needs to be instantiated once and reused across many queries. That's the shape of the thing a future FastAPI service will hold in memory per-process, not a script. Keeping the split makes the eventual API layer a thin wrapper around `app/retrieval` rather than a rewrite of it.
