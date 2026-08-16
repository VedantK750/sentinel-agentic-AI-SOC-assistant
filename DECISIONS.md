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

## 2026-08-16 — Document schema refactor: `{document_id, doc_type, source, title, content, metadata}`

**Decision:** Every document in `documents.json` now has exactly six top-level fields — `document_id`, `doc_type`, `source` (an object, provenance only), `title`, `content`, `metadata` — replacing the old flat `{id, title, content, source, raw}` shape. `parse_mitre.py` and `parse_sigma.py` were rewritten to populate it; `index_bm25.py`, `index_qdrant.py`, and the entire `app/retrieval/` layer were updated to consume the new field names.

**Why now, before Phase 5:** flagged as a deferred gap after Phase 4 — closing it before the intent router (Phase 5) and generation (Phase 6) avoids retrofitting the parsers, both indexers, and every retrieval file a second time once more code depends on the old shape. See the "Phase 1 schema gap" explanation from the prior conversation turn for the concrete problems this fixes (Sigma `tags` → ATT&CK technique mappings were sitting unparsed in a raw YAML blob; MITRE `kill_chain_phases` → tactic was being discarded entirely).

**Design choices:**
- **`document_id` is namespaced and stable**: `mitre_attack:T1059`, `sigma:<rule-uuid>` — globally unique across doc types by construction (source-specific IDs alone aren't guaranteed unique once more sources join the corpus), while the original source-specific ID is *also* preserved unambiguously in `metadata` (`technique_id`, `rule_id`) rather than needing to be parsed back out of the composite ID string.
- **`source` is provenance-only, never identity or type.** It's `{"name": ..., "url"/"repo"/"path": ...}` — enough to trace a document back to exactly where it came from (MITRE's URL for that technique; the Sigma rule's file path within the cloned repo), but the code never branches on it. That's what `doc_type` is for. Conflating "where it's from" with "what it is" was the root cause of the old schema's `source == "SigmaHQ Sigma"` string-equality checks scattered through `parse_sigma.py`'s merge logic — replaced with `doc_type != "detection_rule"`, which stays correct as more sources are added per type.
- **`content` stays pure search text; structure moves to `metadata`.** Nothing that should be filtered or joined on (technique ID, tactic, log source, ATT&CK mapping) lives only in `content` anymore — it's extracted into `metadata` as real fields, while `content` keeps just enough of that information in prose form (e.g. `"Tags: attack.discovery, attack.t1082"` appended to a Sigma rule's content) to stay useful for BM25/embedding search, which was already working well and shouldn't regress.
- **Sigma's `raw` YAML moved into `metadata.raw`** — demoted from "the only place the tags/logsource/etc. live" to "one metadata field among several, kept for traceability." Nothing parses `content` or `raw` to *extract* structure anymore; extraction happens once, in the parser, into dedicated fields.
- **Extensibility validated by design, not by building the corpora yet**: runbooks and synthetic alerts (PLAN §4.3/§4.4) are still unbuilt, but the schema was checked against both shapes on paper (documented in ARCHITECTURE.md) — a `doc_type: "runbook"` or `"security_alert"` document needs no change to the six top-level fields, only a different `metadata` shape, and no change at all to the indexers or retrievers (which never touch `metadata` internals, only pass it through).

**Verified non-regression:** after rebuilding both indices and rerunning the exact same smoke queries used throughout Phase 2–4, BM25 scores, RRF fusion output, and reranker scores are numerically identical to pre-refactor runs (only the `id` values changed shape, e.g. `T1059` → `mitre_attack:T1059`) — confirming this was a pure schema/plumbing change with no effect on ranking behavior. The full retrieval eval (`scripts/evaluate_retrieval.py`) reproduces the exact same aggregate table (BM25 recall@10 0.645, RRF+rerank 0.682/MRR 1.000) as the pre-refactor run documented above.

**New:** `scripts/validate_documents.py` checks required fields, `document_id` uniqueness, and — the part that actually matters — that extraction is *working*: ≥95% of `attack_technique` docs must have non-empty `metadata.tactics` (measured: 100%), ≥50% of `detection_rule` docs must have non-empty `metadata.attack_techniques` (measured: 89%). The 50% floor is deliberately well below the measured 89% — not every Sigma rule maps to an ATT&CK technique, so the check verifies extraction isn't broken, not that coverage is complete.

---

## 2026-08-16 — Cross-encoder reranker: `cross-encoder/ms-marco-MiniLM-L-6-v2`, general-purpose not domain-tuned

**Decision:** Rerank RRF's top candidates with `cross-encoder/ms-marco-MiniLM-L-6-v2` via `sentence-transformers.CrossEncoder` (`app/retrieval/reranker.py`), rather than a security-domain-tuned reranker or a larger cross-encoder.

**Why:**
- It's small (~80MB) and fast enough to rerank 20 candidates per query with no meaningful latency budget concern, matching PLAN §10's instruction to "only rerank a limited candidate set to keep latency reasonable."
- It's the standard, well-benchmarked baseline cross-encoder (trained on MS MARCO passage ranking) — a reasonable default when no security-domain-labeled pair data exists to fine-tune one.
- Same `sentence-transformers` dependency already used for the bi-encoder (`all-MiniLM-L6-v2`), no new library.

**Known limitation, confirmed empirically:** this model has no security-domain knowledge. Smoke-testing `T1059` (see `python -m app.retrieval.reranker`) pulled "Malicious IP Address Sign-In Suspicious" up to rank 3 — a generic-language match, not a real technique-ID relevance signal. The eval results below quantify that this is a net win on average, but it's not uniformly correct. A future domain fine-tune (on ATT&CK/Sigma query→doc pairs) is the natural next improvement once there's enough labeled data — tracked as a future-ideas item, not required for the current phase.

**Result carries `initial_rank`, `reranker_score`, and `final_rank` per PLAN §10**, so the eval script and any future debugging can see exactly how much reranking moved a given doc.

---

## 2026-08-16 — Retrieval eval set uses title-substring relevance rules, not hand-labeled judgments

**Decision:** `scripts/evaluate_retrieval.py` judges a document "relevant" to one of PLAN §11's ten fixed queries via a title-substring rule (e.g. `"mimikatz"` relevant ⇔ title contains "mimikatz"; `"T1059"` relevant ⇔ `id == "T1059"` exactly) rather than manually hand-picking a gold relevance set per query.

**Why:**
- No labeled relevance data exists for this corpus yet, and hand-labeling is subjective and easy to unconsciously bias toward whichever retriever you eyeballed first.
- A rule expressed in code is transparent, reproducible, and automatically stays in sync if the corpus changes (rerun the script, judgments regenerate) — a hardcoded ID list would silently go stale.
- Explicit tradeoff accepted: title-substring matching is a proxy, not true relevance. It undercounts docs that are relevant in content but don't happen to repeat the query term in the title, and overcounts near-miss titles that share vocabulary without matching intent. Good enough to compare *retrieval methods against each other* on equal footing (which is the eval's actual purpose per PLAN §11 — "demonstrate why hybrid retrieval was chosen"), not good enough to claim absolute recall/precision numbers as ground truth.

**Results (K=10, aggregate over 10 queries):**

| method | Hit@10 | Recall@10 | MRR |
|---|---|---|---|
| BM25 only | 1.000 | 0.645 | 1.000 |
| Vector only | 0.900 | 0.494 | 0.764 |
| RRF (BM25+vector) | 1.000 | 0.645 | 0.933 |
| RRF + cross-encoder rerank | 1.000 | **0.682** | 1.000 |

The clearest single data point: for the exact-ID query `"T1059"`, vector-only search scores **0.00 on every metric** — the embedding model doesn't retrieve the technique at all in its top 10. BM25 and RRF recover it perfectly. This is direct, measured confirmation of the reasoning in the RRF decision above (not just the a-priori argument) — hybrid retrieval isn't optional here, vector-only search has a real blind spot on this corpus. Reranking then adds a further, smaller lift on top of RRF (+0.037 recall@10, MRR 0.933 → 1.000), consistent with reranking's job being precision refinement on an already-reasonable candidate set rather than a substitute for retrieval.

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
