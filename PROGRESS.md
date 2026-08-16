# Progress Checklist

Phases derived from [PLAN.md](PLAN.md), ordered by build dependency (roughly the order PLAN.md already lays them out in). Each phase lists the concrete deliverables from the plan, checked off against what's actually in the repo today — not what's intended.

**Legend:** `[x]` done · `[~]` partially done / deviates from plan · `[ ]` not started

---

## Status at a glance

| Phase | Name | Status |
|---|---|---|
| 0 | Project Scaffolding | `[~]` in progress |
| 1 | Knowledge Base Ingestion | `[~]` in progress |
| 2 | Indexing Pipeline | `[~]` in progress |
| 3 | Retrieval — Dense, Lexical, Hybrid RRF | `[x]` done |
| 4 | Reranking & Retrieval Evaluation | `[x]` done |
| 5 | Intent Routing & Agent/Tool Layer | `[x]` done (initial slice) |
| 6 | Generation & Groundedness | `[ ]` not started |
| 7 | RBAC, Guardrails, Propose→Confirm→Execute | `[ ]` not started |
| 8 | Persistence, Audit, API Layer | `[ ]` not started |
| 9 | Frontend & Observability | `[ ]` not started |
| 10 | Testing, CI/CD, Deployment, Hardening | `[ ]` not started |
| 11 | Final Demo Scenario | `[ ]` not started |

**Phase 5 is done.** Retrieval (Phases 2-4), the document schema refactor, metadata-filtered retrieval (closing the last Phase 3 gap), and now the intent router + tool layer are all built, wired together, and verified end to end via `app/agent/orchestrator.py`. Building the router's first natural-language query also surfaced and fixed a real latent bug in BM25 tokenization (see [DECISIONS.md](DECISIONS.md)) that had been silently present since Phase 2. **Next up: Phase 6** (generation + groundedness) — see "Recommendation" at the bottom.

---

## Phase 0 — Project Scaffolding *(PLAN §33)*

- [x] `requirements.txt` with core deps (fastapi, uvicorn, sentence-transformers, qdrant-client, rank-bm25, pydantic, pyyaml, pysigma)
- [x] `data/`, `scripts/`, `app/retrieval/` directories exist
- [x] `git init` — repo initialized, `.gitignore` excludes `.venv/`, build artifacts (`documents.json`, BM25/Qdrant indices), the cloned `data/sigma/` repo, and the raw `enterprise-attack.json` dump (51MB, no fetch script yet)
- [~] `README.md` — currently a one-line stub, not project-descriptive
- [ ] `app/api/`, `app/agent/`, `app/generation/`, `app/actions/`, `app/auth/`, `app/database/`, `app/audit/`, `frontend/`, `tests/`, `docker-compose.yml`, `Dockerfile` — none of these exist yet (expected; later phases)

## Phase 1 — Knowledge Base & Data Ingestion *(PLAN §4, §5)*

- [x] **4.1 MITRE ATT&CK** — `scripts/parse_mitre.py` extracts `attack-pattern` objects from the STIX bundle → 858 docs
- [~] **4.2 Sigma Rules** — `scripts/parse_sigma.py` clones SigmaHQ and parses rule YAML → 3,137 docs. *Deviation:* plan calls for parsing "with the Sigma ecosystem/pySigma where practical"; current implementation uses plain `yaml.safe_load`, not `pysigma` (which sits unused in requirements.txt). Good enough for indexing text, but no rule validation or backend-target translation.
- [ ] **4.3 Security Runbooks** — no runbook corpus yet (plan wants ~9 Markdown runbooks: PowerShell investigation, credential dumping, phishing, suspicious login, malware, ransomware, endpoint isolation, malicious IP response, incident escalation). Schema is ready to receive a `doc_type: "runbook"` — see ARCHITECTURE.md — but the corpus itself isn't written.
- [ ] **4.4 Alert/Event Data** — no synthetic alert/event corpus yet (Sysmon, auth failures, Suricata, etc.). Same story: schema-ready (`doc_type: "security_alert"`), corpus not built.
- [x] **Document normalization (§5)** — every document now has the canonical `{document_id, doc_type, source, title, content, metadata}` shape. MITRE docs carry `technique_id`/`tactics`/`platforms`/`parent_technique_id` in `metadata`; Sigma docs carry `attack_techniques`/`attack_tactics` (parsed out of `tags`, no longer just inert text)/`logsource`/`references`/`raw`. Full rationale in [DECISIONS.md](DECISIONS.md), schema examples in [ARCHITECTURE.md](ARCHITECTURE.md).
- [x] Schema validation — `scripts/validate_documents.py` checks required fields, `document_id` uniqueness, and that extraction actually worked (measured: 100% of MITRE docs have tactics, 89% of Sigma docs have ATT&CK technique mappings)

## Phase 2 — Indexing Pipeline *(PLAN §6)*

- [x] Loads normalized documents from `documents.json`
- [x] Generates embeddings (`scripts/index_qdrant.py`)
- [x] Stores embeddings + metadata in Qdrant
- [x] Tokenizes documents for lexical search
- [x] Builds and persists BM25 index (`scripts/index_bm25.py`)
- [x] Reproducible — both scripts are idempotent re-runs from `documents.json`
- [ ] Corpus/index version recorded (e.g. a version stamp or doc-count/hash written alongside the index) — not implemented; no way to tell if an index is stale relative to `documents.json` without rebuilding

## Phase 3 — Retrieval: Dense, Lexical, Hybrid RRF *(PLAN §7, §8, §9)* — DONE

- [~] **Dense retrieval (Qdrant)** — `app/retrieval/vector_retriever.py`. *Deviation:* plan specifies `BAAI/bge-small-en-v1.5`; current implementation uses `all-MiniLM-L6-v2` (carried over from the original indexing script). Both are reasonable small sentence-transformer models — a documented choice, not a gap, so it doesn't block calling this phase done.
- [x] Metadata filtering (only-MITRE / only-Sigma / only-attack_technique / only-detection_rule search) — `doc_type` param added to `BM25Retriever.search`/`VectorRetriever.search`/`HybridSearcher.search`. BM25 post-filters candidates before truncating to `limit`; Qdrant uses a native `Filter`/`MatchAny` during the ANN search itself. Verified: filtering "credential dumping" to `attack_technique` vs `detection_rule` returns disjoint, correctly-typed result sets.
- [x] **Lexical retrieval (BM25)** — `app/retrieval/bm25_retriever.py`, returns document_id/rank/score. Tokenizer now strips English stopwords — see the bug entry in [DECISIONS.md](DECISIONS.md); this was found and fixed during Phase 5, not here, but belongs to this phase's component.
- [x] **Hybrid RRF** — `app/retrieval/fusion.py` + `app/retrieval/hybrid.py`, configurable `k` (default 60), documented in [DECISIONS.md](DECISIONS.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
- [x] Fused result exposes rank per retriever (plan §9 requirement) — `reciprocal_rank_fusion` now takes a `{name: ranked_list}` dict and returns a `"ranks"` field per doc, e.g. `{"bm25": 2, "vector": 7}`, with entries omitted for retrievers that didn't return the doc. Verified against live queries: `T1059` resolves via BM25 alone (vector's #1 for that query is the false friend `T1065`), giving a concrete "one retriever wins" example for the Phase 4 eval.

## Phase 4 — Reranking & Retrieval Evaluation *(PLAN §10, §11)* — DONE

- [x] Cross-encoder reranker over RRF's top candidates — `app/retrieval/reranker.py`, `cross-encoder/ms-marco-MiniLM-L-6-v2` (general-purpose, not domain-tuned — see [DECISIONS.md](DECISIONS.md))
- [x] Expose initial rank / reranker score / final rank per result
- [x] Fixed evaluation query set (originally T1059, credential dumping, powershell execution, curl file upload, mimikatz, ransomware, phishing, lsass, disable defender, reverse shell; extended in Phase 5 to 11 queries — see below) — `scripts/evaluate_retrieval.py`
- [x] Compare BM25-only vs. vector-only vs. RRF vs. RRF+cross-encoder (later extended to RRF+cross-encoder+exact-match-boost in Phase 5)
- [x] Track Recall@K, Hit@K, MRR (K=10)
- [x] Keep qualitative "one retriever wins, other fails" examples — `T1059` is a **complete vector-only failure** (0.00 on every metric), fully recovered by BM25/RRF; see [DECISIONS.md](DECISIONS.md) for the full results table

**Aggregate results as first measured (K=10, original 10-query set):** BM25 recall@10 0.645 / vector 0.494 / RRF 0.645 (MRR 0.933) / RRF+rerank **0.682 recall@10, 1.000 MRR** — reranking gives a further lift on top of RRF as expected, confirming the hybrid+rerank pipeline over either single method. Relevance judgments are a title-substring heuristic, not hand-labeled — see DECISIONS.md for why and its limits. *(These numbers moved slightly after Phase 5's BM25 stopword fix and the added 11th query — current numbers are in the Phase 5 section below and in DECISIONS.md; the methodology and conclusion are unchanged.)*

## Phase 5 — Intent Routing & Agent/Tool Layer *(PLAN §12, §13)* — DONE (initial slice)

- [x] Intent router — `app/agent/router.py`, `IntentRouter`. 5 intents (`explain_technique`, `search_detection_rule`, `search_knowledge_base` read; `block_ip`, `isolate_endpoint` write), deliberately smaller than PLAN's full 20+-intent read/write list per §12's own instruction to "start with a smaller set and make the architecture extensible" — the remaining PLAN-listed intents (investigate alert, lookup IOC, search runbook, explain log, summarize incident, search threat intel, create incident, add IOC, close incident) aren't routable yet because their backing data/tools don't exist (Phase 1 runbooks/alerts, Phase 8 incidents).
- [x] Confidence-aware cascade (lexical/keyword signal → semantic similarity vs. example utterances → combined score → confidence **and** margin threshold, stricter for write intents → `clarify` when uncertain) — matches PLAN §12's cascade exactly. Verified against deliberately adversarial queries: `"block"` alone correctly falls to `clarify` (0.54 vs the 0.55 write threshold); `"What sigma rule covers T1003"` correctly falls to `clarify` on a margin tie between two legitimately valid intents, not a confidence failure.
- [x] Tool definitions with schema, typed (pydantic) input, authz requirement (declared, not yet enforced), side-effect classification, idempotency behavior (declared), audit event (declared) — `app/agent/tools.py`, all 8 of PLAN §13's initial tools registered.
- [x] Mocked/local tool implementations — 2 real (`search_knowledge_base`, `search_sigma_rules`, both backed by the full RRF+rerank+boost pipeline), 3 stubs reporting "no data source yet" (`lookup_ioc`, `get_alert`, `get_incident`), 3 stubs reporting "not executed, RBAC/confirm pipeline not built" (`create_incident`, `block_ip`, `isolate_endpoint`).
- [x] `app/agent/orchestrator.py` ties router + registry together end to end (`Orchestrator.handle(query)`), verified against real queries.

**Two retrieval-quality issues found and fixed while building this:**
1. The router's first real natural-language query (`"What is T1059?"`) exposed a latent defect in BM25 tokenization present since Phase 2 — classic Okapi BM25's IDF goes negative for stopwords appearing in most of the corpus, so "is"/"what" were actively penalizing correct results, invisible until a query used them. Fixed by stopword-filtering `tokenize()` (now a single shared function, previously duplicated between `scripts/index_bm25.py` and `app/retrieval/bm25_retriever.py`).
2. Even after that fix, natural-language exact-ID questions could still get out-ranked by RRF/reranking (RRF can't tell "exact match at rank 1" from "happened to be rank 1" — it only sees rank, not score magnitude). Added `app/retrieval/exact_match.py`'s `ExactMatchBooster`: detects known-item identifiers (technique IDs, Sigma rule UUIDs) in the query and pins an exact corpus match to the front of the result list, as an explicit final pipeline stage (not folded into RRF/reranking, so those keep meaning what Phase 4 measured). Added a 5th `rrf+rerank+boost` eval column and a query specifically shaped to test this (`"What is T1003.001?"`) — measured result: RRF+rerank alone scored **0.00 on every metric** for that query (the reranker pushed the correct doc out of the top 10 entirely), boosting recovers a perfect 1.00/1.00/1.00. Aggregate over the eval set also improved (Hit@10 1.000, Recall@10 0.715, MRR 1.000 vs RRF+rerank's 0.909/0.625/0.909).

Full writeups of both in [DECISIONS.md](DECISIONS.md).

**Scope boundary, explicit:** the router classifies intent; it does not extract structured arguments (target IP, hostname) from write queries. For write intents, `Orchestrator` reports the classification and stops — there's no RBAC/confirm/execute pipeline (Phase 7) to hand off to yet, so building slot-filling now would be building for a stage that doesn't exist.

## Phase 6 — Read Workflows: Generation & Groundedness *(PLAN §14, §15, §16)*

- [ ] LLM generation constrained to retrieved evidence only
- [ ] Citation format (`[T1059] MITRE ATT&CK`, `[Sigma: <rule-id>] ...`)
- [ ] "Insufficient evidence" fallback response
- [ ] Groundedness judge (post-generation check that claims are supported)
- [ ] Regenerate-or-reject path when ungrounded

## Phase 7 — RBAC, Guardrails, Propose→Confirm→Execute *(PLAN §17–§21)*

- [ ] Roles (`analyst`, `senior_analyst`, `admin`) and permissions (`knowledge.read`, `alerts.read`, `incidents.read`, `incidents.create`, `network.block_ip`, `endpoint.isolate`)
- [ ] Authorization check on every tool call
- [ ] Fail-closed behavior (deny on: authz service down, missing identity, missing permission, malformed request, missing confirmation, unknown tool, invalid target)
- [ ] Propose → confirm → re-check authz → idempotency check → execute → audit workflow
- [ ] Mock firewall (`block_ip`/`unblock_ip`), mock EDR (`isolate_endpoint`/`release_endpoint`), mock incident system (`create_incident`/`update_incident`)
- [ ] Idempotency keys backed by PostgreSQL — duplicate submission returns the original result, doesn't re-execute

## Phase 8 — Persistence, Audit, API Layer *(PLAN §22–§25)*

- [ ] Audit event schema (timestamp, user_id, role, intent, tool, action, target, authz result, confirmation, execution result, idempotency key, request ID) persisted immutably
- [ ] PostgreSQL schema: users, roles, permissions, incidents, actions, confirmations, idempotency keys, audit events
- [ ] FastAPI endpoints: `POST /chat`, `POST /search`, `POST /intent`, `POST /actions/propose`, `POST /actions/{id}/confirm`, `GET /alerts/{id}`, `GET /incidents/{id}`, `GET /audit` — **none exist yet**, `app/` currently contains only `retrieval/`
- [ ] Pydantic request/response schemas for every endpoint
- [ ] Conversation/agent state for proposal→confirmation→execution (with expiring confirmations)

## Phase 9 — Frontend & Observability *(PLAN §26, §27)*

- [ ] Minimal React frontend: chat view w/ citations, retrieval evidence panel, action proposal confirm/reject UI, audit log view
- [ ] Structured logging with request ID per request
- [ ] Per-stage latency logging (intent, BM25, Qdrant, RRF, reranker, LLM, tool execution)

## Phase 10 — Testing, CI/CD, Deployment, Hardening *(PLAN §28–§31)*

- [ ] Tests: retrieval (exact lookup, semantic, Sigma, empty results, mixed-source), intent (known/ambiguous/low-confidence/dangerous), authz (permitted/denied/missing role/missing permission/service failure), confirmation (confirmed/rejected/expired/missing), idempotency (repeat/duplicate/retry), grounding (supported/unsupported/no evidence)
- [ ] GitHub Actions: lint, unit tests, integration tests, type checks, build — **no CI possible yet, repo isn't even a git repo**
- [ ] Dockerfile + docker-compose (FastAPI, PostgreSQL, Qdrant, frontend) — single-command startup
- [ ] Security hardening pass: input validation, identifier sanitization, server-side authz enforcement, short-lived confirmation tokens, restricted tool schemas, secret redaction in logs, request timeouts, safe LLM/tool failure handling

## Phase 11 — Final Demo Scenario *(PLAN §32)*

- [ ] Scripted end-to-end walkthrough: investigate alert → retrieve technique/Sigma/runbook → cited explanation → propose IP block → confirm → RBAC/idempotency/mock-firewall/audit → success response with audit ID

---

## Recommendation: what to do next

Retrieval (Phases 2-4), the document schema, and the intent router + tool layer (Phase 5) are all done and verified now. **Move to Phase 6** (generation + groundedness): the router already routes a confident read query to a tool that returns ranked evidence — the missing piece is turning that evidence into an actual cited answer instead of a raw result list, which is what `Orchestrator`'s output is standing in for right now.

Deliberately still deferred, not because they're hard but because nothing downstream needs them yet:
- **Runbooks and alert/event data** (rest of Phase 1) — schema-ready, corpus not built; worth doing once a `search_runbook`/`investigate_alert` intent actually needs something to search.
- **Entity/slot extraction for write intents** (surfaced explicitly in Phase 5) — needed before Phase 7's propose-confirm-execute can do anything with a classified write intent, but building it before Phase 7 exists means building for a pipeline stage with nothing to hand off to.
- **RRF `k` retuning for natural-language exact-ID queries** (surfaced while fixing the BM25 bug, see DECISIONS.md) — a characterized, not fixed, limitation. Worth a dedicated pass through the eval script if it matters enough, not a side effect of unrelated work.
