# Decisions

A running log of non-obvious technical decisions: what was chosen, why, and what was ruled out. Newest first.

---

## 2026-08-17 — Consolidated document-loading into `app/retrieval/documents.py`

**Decision:** `load_documents()` / `load_content_by_id()` now live in one file. `CrossEncoderReranker`, `ExactMatchBooster`, and `GroundednessJudge` all import from it instead of each having their own copy of "read `documents.json`, build an `id -> content` dict."

**Why:** about to write a fourth independent copy of the same seven lines for the groundedness judge — and this project already has a concrete example of what duplicated "load and index the same data" logic costs: the BM25 tokenizer bug (see below) existed specifically because `tokenize()` was copy-pasted instead of shared, and index-time/query-time silently drifted apart. Same risk shape here (three-plus components independently parsing the same corpus file), so consolidated proactively rather than waiting for a second version of that bug.

---

## 2026-08-17 — Phase 6: generation uses a non-Anthropic LLM (user-provided endpoint), not the Claude API

**Decision:** `app/generation/generator.py` calls `deepseek/deepseek-v4-flash` via a third-party OpenAI-compatible proxy (`https://aicredits.in/v1`), using the `openai` Python SDK pointed at a custom `base_url`, with credentials from a local `.env` file (`LLM_API_KEY`, `LLM_ENDPOINT`) loaded via `python-dotenv`.

**Why not Anthropic:** the user has existing API credits/access for this specific provider and asked for it by name. Anthropic's SDK only talks to Anthropic's API — using it here would mean either ignoring the user's actual credentials or silently building something that can't run. The OpenAI-compatible `chat.completions` shape is what this proxy speaks, so that's the client used.

**Immediate operational finding:** `.env` was present in the repo but **not gitignored** — caught and fixed (added to `.gitignore`) before any commit, since the API key would otherwise have been pushed to git history on the next `git add -A`. Worth calling out explicitly: this is exactly the kind of thing the "review what's staged before committing" habit exists to catch, and it did.

**A real gotcha found via testing, not assumed:** this endpoint serves a reasoning model that emits hidden `reasoning_content` tokens (its chain-of-thought) billed against the *same* `max_tokens` budget as the visible `content` — there's no separate thinking-budget parameter the way Anthropic's `thinking` config provides. A first test at `max_tokens=100` silently truncated a two-line JSON reply (`finish_reason: "length"`, `content: '{"status'`) because ~97 of the 100 tokens went to invisible reasoning. Fixed by using `max_tokens=2048` for generation calls and reading only `.content`, never `.reasoning_content`. Documented in `generator.py` itself since this is exactly the kind of provider-specific constraint that bites the next person editing the file without reading history first.

**Structured output, verified working:** `response_format={"type": "json_object"}` reliably produces valid JSON matching the `GeneratedAnswer` Pydantic schema (a list of `{text, cited_document_ids}` claims + an `insufficient_evidence` flag) — confirmed by direct testing with a real query and real retrieved evidence, correctly attributing each claim to the right document, before writing any of the surrounding pipeline code.

---

## 2026-08-17 — Groundedness judge: NLI model swapped after real evidence it didn't work

**Decision:** `app/generation/groundedness.py`'s `GroundednessJudge` uses `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`, not the originally-planned `cross-encoder/nli-deberta-v3-base`.

**What happened:** built the judge exactly as scoped earlier (NLI cross-encoder, premise = cited document content, hypothesis = claim text, entailment probability vs. a threshold) with `cross-encoder/nli-deberta-v3-base` — the first NLI checkpoint that came to mind, same `sentence-transformers` CrossEncoder pattern already validated for reranking. Tested it against a claim that was a **near-verbatim restatement of the actual document text** — about as clear an entailment case as exists. It scored entailment probability **0.003**, classifying the pair as "neutral." Not a marginal miss — a claim that should obviously pass was rejected by a wide margin.

**Root cause, diagnosed rather than papered over:** that checkpoint is trained on SNLI/MultiNLI — short, generic, single-sentence premise/hypothesis pairs (image captions, everyday sentences). Fed a full technical paragraph as the premise (our actual use case: document content vs. a claim), it's out-of-distribution and doesn't reliably recognize entailment even for near-identical phrasing in specialized (cybersecurity) text. Verified this wasn't a bug in my usage first — checked `model.config.id2label` for the correct index, tried both argument orders, and confirmed the model scores a classic textbook SNLI pair correctly (0.975 entailment) — so the model works as documented, it just doesn't transfer to this task.

**Fix:** switched to `MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli` — trained on MNLI **plus FEVER** (a claim-vs-evidence-passage fact-verification dataset) **plus ANLI** (adversarially-constructed hard examples). FEVER's task shape — "does this evidence passage support this claim" — is a direct match for RAG groundedness checking, unlike generic short-sentence NLI. Re-tested the same near-verbatim claim: **entailment probability 0.983**. Also correctly separated a misattribution case (a true statement, but citing the wrong document — the parent technique instead of the subtechnique that actually says it) as contradiction (0.839), and a fabricated-citation case as unsupported (empty evidence text, never reaches the model). This checkpoint's label order is **different** from the first one (`{0: entailment, 1: neutral, 2: contradiction}` vs. the first model's `{0: contradiction, 1: entailment, 2: neutral}`) — re-verified empirically rather than assumed, since copy-pasting the index from the first model would have silently inverted every verdict on the second.

**Why this matters beyond "picked a better model":** this is the same *type* of lesson as the BM25 stopword bug — a component that looked correct in isolation (documented API, right index, right label names) failed on the actual data shape this project needed, and the fix was found by testing against a real example with a known-correct answer, not by reading further documentation. The general takeaway carried forward: verify a model or library against a *concrete example with a known-correct answer specific to your domain*, not just its own documented behavior on its own benchmark.

**End-to-end validation of the full pipeline** (`app/generation/pipeline.py`, which ties generation + judge + regen-or-reject together): three test queries exercised all three of PLAN §16's required behaviors in one run —
- `"How do I detect mimikatz?"` — first attempt had an ungrounded claim, retried with the failure named explicitly, second attempt fully grounded (the regen path).
- `"What is T1059?"` — after retry, some claims verified and some didn't; the ones that didn't were dropped, not silently kept (the partial-fallback path).
- `"What is the airspeed of a swallow?"` — zero relevant evidence exists for this query; the model correctly returned `insufficient_evidence: true` with no claims at all on the *first* attempt, rather than fabricating something — no retry needed because there was nothing wrong to retry.

---

## 2026-08-16 — Exact-match boosting for known-item queries (`app/retrieval/exact_match.py`)

**Decision:** Added `ExactMatchBooster` as an explicit final stage after RRF+rerank: it detects known-item identifiers in the query (ATT&CK technique IDs, Sigma rule UUIDs — a registry of `(regex pattern, metadata field)` pairs, extensible to IOCs later) and, if the corpus has a document with that exact ID, pins it to the front of the result list. Deliberately a separate stage, not folded into `HybridSearcher` or the reranker — the same reasoning as keeping reranking separate from RRF: BM25/vector/RRF/RRF+rerank keep meaning exactly what the Phase 4 eval already measured, and this stage's own effect is independently measurable (`scripts/evaluate_retrieval.py` now has a fifth `rrf+rerank+boost` column).

**Why this is a different fix from retuning `k`:** RRF only sees rank position, never raw score, so it can't distinguish "BM25 rank #1 because this is a near-unique exact token match" from "BM25 rank #1 because it edged out rank #2 by a hair." An exact identifier match is about as unambiguous as retrieval evidence gets — this makes that certainty explicit instead of hoping fusion/rerank parameters happen to preserve it. Retuning `k` globally would change behavior for every query, including the ones where RRF's "combine evidence across retrievers" design is already correct (most of what Phase 4 validated); this only activates for the narrow, well-defined case of a detected exact identifier.

**Implementation:** loads `documents.json` once at construction to build `{metadata_field: {normalized_id_value: document}}` lookup tables (same one-time-load pattern as `CrossEncoderReranker`'s content lookup). `.detect(query)` finds identifier matches; `.boost(query, results, limit)` prepends them (deduplicated against `results`) and truncates to `limit`. A detected exact match is injected even if the upstream pipeline didn't return it at all — correct by construction, not just highly ranked. Wired into `app/agent/tools.py`'s `_search()` as the final pipeline stage; the reranker now reranks a wide candidate set (`RERANK_CANDIDATE_LIMIT=20`) rather than truncating straight to the requested limit, so boosting has enough non-exact-match results left to fill out the final list after prepending.

**Measured, not assumed:** the existing eval set didn't exercise this at all — none of its 10 queries were natural-language exact-ID questions (all short keyword phrases). Added `"What is T1003.001?"` specifically to test this query shape, and the result is dramatic:

| method | Hit@10 | Recall@10 | MRR |
|---|---|---|---|
| BM25 | 1.00 | 1.00 | 1.00 |
| Vector | 0.00 | 0.00 | 0.00 |
| RRF | 1.00 | 1.00 | 0.50 |
| RRF+rerank | **0.00** | **0.00** | **0.00** |
| RRF+rerank+boost | 1.00 | 1.00 | 1.00 |

RRF+rerank doesn't just under-rank T1003.001 for this query — it drops it out of the top 10 **entirely**. The reranker's non-domain-tuned scoring (already documented as a known limitation) actively made this worse, not just neutral. Boosting recovers perfect scores regardless of what the upstream pipeline did. Aggregate over the now-11-query eval set: RRF+rerank+boost reaches **1.000 Hit@10 / 0.715 Recall@10 / 1.000 MRR**, clearly ahead of RRF+rerank's 0.909/0.625/0.909 — a real, measured improvement, not just a fix for one cherry-picked query.

---

## 2026-08-16 — Bug found and fixed while building Phase 5: BM25 stopwords had negative weight

**What happened:** building the intent router's `explain_technique` tool exposed the first natural-language question ever run through BM25 end-to-end (`"What is T1059?"` — every prior query, in every eval and demo, was a short keyword phrase like `"T1059"` or `"curl file upload"`, never a full grammatical question). That query returned `T1070.004 File Deletion` as the top `attack_technique` result — a document with no relation to T1059 at all — instead of T1059 itself.

**Root cause:** classic Okapi BM25's IDF term is `log((N - n(t) + 0.5) / (n(t) + 0.5))`, which goes **negative** once a term appears in more than half the corpus. Words like "is" and "what" appear in nearly every one of the 858 ATT&CK technique descriptions, so for the query `"what is t1059"`, those two terms didn't just contribute nothing — they actively subtracted score from any document that happened to use them a lot, which most fluently-written technique descriptions do. The single correctly-matching term ("t1059") wasn't enough to overcome the penalty from the other two.

**Why this stayed hidden through Phase 2-4:** every query used anywhere in this project up to this point (the eval set, every retrieval demo, every reranker smoke test) was a short keyword-style phrase with no stopwords. Phase 5 is the first place a full sentence hit `BM25Retriever` — this was a latent defect in `tokenize()` since Phase 2, only surfaced by the first natural-language caller.

**Fix:** added a small hardcoded English stopword list (~80 words) and filter it out at tokenization. Also collapsed `tokenize()` from two copies (`scripts/index_bm25.py` had its own duplicate of `app/retrieval/bm25_retriever.py`'s function) into one — `index_bm25.py` now imports it — because the bug case is exactly why two copies is dangerous: index-time and query-time tokenization must always match exactly, or the index and the query silently speak different languages. Documented in the function itself, not just here, since anyone editing it needs the warning at the point of edit.

**Verified:** `"What is T1059?"` now returns T1059 as `BM25Retriever`'s #1 result. Re-ran the full `scripts/evaluate_retrieval.py` suite afterward — aggregate numbers are flat to very slightly improved (RRF+rerank recall@10 0.682 → 0.687), confirming the fix doesn't regress anything the eval set already validated.

**Residual limitation found (later fixed, not here):** even after the stopword fix, `"What is T1059?"` through the *full* RRF+rerank pipeline still didn't put T1059 at rank 1 (BM25 alone got it right; RRF and the reranker both nudged it down). Two already-documented properties compounding on this specific query shape:
- RRF's design (see the RRF decision above) rewards a document found by *both* retrievers over one found by only one, even at a worse individual rank. Here T1059 was BM25's #1 but absent from vector's top 50 entirely, while a semantically-nearby-but-wrong document appeared moderately in both lists and out-scored it under `k=60`.
- The reranker (see the reranker decision above) is a general-purpose model with no security-domain knowledge, and didn't reliably fix this either.
Deliberately not addressed by retuning `k` or the reranker — that would change already-eval-validated Phase 4 numbers without re-running that validation. Instead fixed properly afterward with a dedicated, measured mechanism — see the exact-match boosting decision above.

---

## 2026-08-16 — Phase 5: intent router (`app/agent/router.py`) reuses the hybrid-retrieval pattern

**Decision:** Classify a query into one of a small set of intents using the same lexical+semantic combination retrieval already uses — a keyword/regex signal, a sentence-embedding similarity signal against per-intent example utterances, combined and gated by a confidence threshold — rather than training a classifier or hand-writing a rule engine.

**Why:** PLAN §12 specifies exactly this cascade (`lexical/IDF → semantic → hybrid fusion → confidence threshold → escalate/clarify`), and it's the same underlying problem retrieval already solves: matching a query against a small reference set, where exact phrasing and paraphrase both need to work. No labeled intent-classification training data exists, so a trained classifier isn't an option yet; a pure keyword rule engine would miss paraphrases the way BM25-alone misses them in retrieval.

**Confidence gating, asymmetric by category:** the top intent must clear a threshold (`0.35` read / `0.55` write — write requires more confidence) **and** beat the runner-up by a minimum margin (`0.05`), or the router returns `clarify` instead of guessing. Both thresholds needed because either failure mode alone is misleading: a single high score can still be a coin-flip against a near-tied runner-up (e.g. `"What sigma rule covers T1003"` scores 0.79 for `search_detection_rule` — well above threshold — but only edges `explain_technique` by 0.04, below the margin requirement, so it correctly clarifies rather than guessing between two legitimately valid interpretations). The write/read asymmetry is a direct application of PLAN §18's fail-closed principle: misrouting into a read search costs a wasted query, misrouting into a write intent risks proposing the wrong action.

**Verified, including an honest asymmetry left as-is:** `"block"` alone scores 0.54 — just under the 0.55 write threshold — and correctly clarifies instead of committing to `block_ip` with no target specified. `"isolate"` alone, by contrast, scores 0.74 and *does* commit to `isolate_endpoint`, because "isolate" is itself one of `isolate_endpoint`'s keywords and near-verbatim to one of its example phrasings, while "block" only appears embedded in longer examples ("Block this IP address"). This is a real inconsistency in a threshold-based classifier on very short inputs, not hidden here — a case where the router's job (classify *what* the user wants) is intentionally decoupled from a separate, unsolved problem (whether required *arguments* like a target IP/host were actually given), left to a future slot-filling / action-planning layer (PLAN's Action Planner box, Phase 7) rather than papered over here.

**Scope boundary:** the router only classifies. It does not attempt to extract a target IP or hostname from a write-intent query — the orchestrator (`app/agent/orchestrator.py`) reports the classification for write intents and explicitly stops there, since there's no RBAC/confirm/execute pipeline (Phase 7) for it to hand off to yet. Building entity extraction now would be building for a pipeline stage that doesn't exist.

---

## 2026-08-16 — Phase 5: tool layer declares RBAC/idempotency/audit contracts before they're enforced

**Decision:** `app/agent/tools.py`'s `Tool` dataclass carries `required_permission`, `idempotent`, and `audit_event` fields on every tool right now, even though nothing reads or enforces them yet (RBAC is Phase 7, the audit log is Phase 8).

**Why:** PLAN §13 asks for tools to declare "authorization requirements, side-effect classification, idempotency behavior, audit event" as part of the tool's definition, not as something bolted on when RBAC is built. Declaring it now means Phase 7's enforcement layer reads a contract that already exists (`if not user.has_permission(tool.required_permission): deny`) instead of hardcoding tool-specific authorization logic when it's built. Concretely: `block_ip` and `isolate_endpoint` are marked `idempotent=True` because blocking an already-blocked IP (once real execution exists) is a safe no-op, not a compounding action — `create_incident` is marked `idempotent=False` because creating two incidents from one duplicated request is a real bug. That distinction has to be decided per-tool by someone who understands what the tool does; better to decide it once, here, than rediscover it under Phase 7 time pressure.

**Eight tools registered, two backed by real retrieval, six stubbed honestly:** `search_knowledge_base` and `search_sigma_rules` call the full validated Phase 4 pipeline (RRF top-20 candidates → cross-encoder rerank). `lookup_ioc`/`get_alert`/`get_incident` return an explicit "no data source yet" error rather than fabricating a plausible-looking empty result. `create_incident`/`block_ip`/`isolate_endpoint` return `{"status": "not_executed", "reason": "...", "proposed_action": {...}}` — the shape a real propose-confirm-execute flow will eventually consume, without pretending to execute anything.

---

## 2026-08-16 — Metadata filtering added to both retrievers (closes a Phase 3 gap)

**Decision:** `BM25Retriever.search()` and `VectorRetriever.search()` both take an optional `doc_type` parameter now; `HybridSearcher.search()` threads it through to both. Post-filter for BM25 (score all rows, then drop non-matching ones before truncating to `limit`), native Qdrant `Filter`/`MatchAny` for the vector side (filtered during the ANN search itself, not after).

**Why now:** this was flagged as a Phase 3 gap blocked on the schema refactor (`doc_type` didn't exist as a queryable field before). It's needed the moment the tool layer exists: `explain_technique` and `search_sigma_rules` are two different tools precisely because one is `search_knowledge_base` filtered to `attack_technique` and the other is filtered to `detection_rule` — without this, those would have to be two separate, duplicated retrieval code paths instead of one parameterized one.

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
