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
| 3 | Retrieval — Dense, Lexical, Hybrid RRF | `[~]` in progress |
| 4 | Reranking & Retrieval Evaluation | `[ ]` not started |
| 5 | Intent Routing & Agent/Tool Layer | `[ ]` not started |
| 6 | Generation & Groundedness | `[ ]` not started |
| 7 | RBAC, Guardrails, Propose→Confirm→Execute | `[ ]` not started |
| 8 | Persistence, Audit, API Layer | `[ ]` not started |
| 9 | Frontend & Observability | `[ ]` not started |
| 10 | Testing, CI/CD, Deployment, Hardening | `[ ]` not started |
| 11 | Final Demo Scenario | `[ ]` not started |

**Next up: finish Phase 3** (fusion rank metadata + source filtering), or jump straight to **Phase 4** (cross-encoder reranking + eval set) since RRF is functionally working — see "Recommendation" at the bottom.

---

## Phase 0 — Project Scaffolding *(PLAN §33)*

- [x] `requirements.txt` with core deps (fastapi, uvicorn, sentence-transformers, qdrant-client, rank-bm25, pydantic, pyyaml, pysigma)
- [x] `data/`, `scripts/`, `app/retrieval/` directories exist
- [ ] `git init` — **repo is not under version control yet**
- [~] `README.md` — currently a one-line stub, not project-descriptive
- [ ] `app/api/`, `app/agent/`, `app/generation/`, `app/actions/`, `app/auth/`, `app/database/`, `app/audit/`, `frontend/`, `tests/`, `docker-compose.yml`, `Dockerfile` — none of these exist yet (expected; later phases)

## Phase 1 — Knowledge Base & Data Ingestion *(PLAN §4, §5)*

- [x] **4.1 MITRE ATT&CK** — `scripts/parse_mitre.py` extracts `attack-pattern` objects from the STIX bundle → 858 docs
- [~] **4.2 Sigma Rules** — `scripts/parse_sigma.py` clones SigmaHQ and parses rule YAML → 3,137 docs. *Deviation:* plan calls for parsing "with the Sigma ecosystem/pySigma where practical"; current implementation uses plain `yaml.safe_load`, not `pysigma` (which sits unused in requirements.txt). Good enough for indexing text, but no rule validation or backend-target translation.
- [ ] **4.3 Security Runbooks** — no runbook corpus yet (plan wants ~9 Markdown runbooks: PowerShell investigation, credential dumping, phishing, suspicious login, malware, ransomware, endpoint isolation, malicious IP response, incident escalation)
- [ ] **4.4 Alert/Event Data** — no synthetic alert/event corpus yet (Sysmon, auth failures, Suricata, etc.)
- [~] **Document normalization (§5)** — current schema is `{id, title, content, source}`. Plan's canonical schema also wants `doc_type` (e.g. `attack-technique`, `detection-rule`) and a `metadata` object (tactic, sub-technique relationships, source URL, log source, ATT&CK mappings on Sigma rules). Not yet added — will matter once source-filtered retrieval or runbooks/alerts (different `doc_type`s) enter the corpus.

## Phase 2 — Indexing Pipeline *(PLAN §6)*

- [x] Loads normalized documents from `documents.json`
- [x] Generates embeddings (`scripts/index_qdrant.py`)
- [x] Stores embeddings + metadata in Qdrant
- [x] Tokenizes documents for lexical search
- [x] Builds and persists BM25 index (`scripts/index_bm25.py`)
- [x] Reproducible — both scripts are idempotent re-runs from `documents.json`
- [ ] Corpus/index version recorded (e.g. a version stamp or doc-count/hash written alongside the index) — not implemented; no way to tell if an index is stale relative to `documents.json` without rebuilding

## Phase 3 — Retrieval: Dense, Lexical, Hybrid RRF *(PLAN §7, §8, §9)*

- [~] **Dense retrieval (Qdrant)** — `app/retrieval/vector_retriever.py`. *Deviation:* plan specifies `BAAI/bge-small-en-v1.5`; current implementation uses `all-MiniLM-L6-v2` (carried over from the original indexing script). Both are reasonable small sentence-transformer models — worth an explicit decision on which to standardize on rather than leaving it implicit.
- [ ] Metadata filtering (only-MITRE / only-Sigma / only-runbook search) — not implemented; needs `doc_type` in payload (blocked by Phase 1 schema gap) plus a `filter` param on `VectorRetriever.search`
- [x] **Lexical retrieval (BM25)** — `app/retrieval/bm25_retriever.py`, returns id/rank/score
- [x] **Hybrid RRF** — `app/retrieval/fusion.py` + `app/retrieval/hybrid.py`, configurable `k` (default 60), documented in [DECISIONS.md](DECISIONS.md) and [ARCHITECTURE.md](ARCHITECTURE.md)
- [ ] Fused result should expose **both** `bm25_rank` and `dense_rank` per doc (plan §9 requirement) — current `reciprocal_rank_fusion` returns only the fused `rrf_score` plus whichever retriever's dict happened to register the doc first; doesn't yet surface "present in BM25 at rank X, present in dense at rank Y" side by side

## Phase 4 — Reranking & Retrieval Evaluation *(PLAN §10, §11)*

- [ ] Cross-encoder reranker over RRF's top candidates
- [ ] Expose initial rank / reranker score / final rank per result
- [ ] Fixed evaluation query set (T1059, credential dumping, powershell execution, curl file upload, mimikatz, ransomware, phishing, lsass, disable defender, reverse shell)
- [ ] Compare Qdrant-only vs. BM25-only vs. RRF vs. RRF+cross-encoder
- [ ] Track Recall@K, Hit@K, MRR
- [ ] Keep qualitative "one retriever wins, other fails" examples

## Phase 5 — Intent Routing & Agent/Tool Layer *(PLAN §12, §13)*

- [ ] Intent router (read intents: explain technique, search detection rule, investigate alert, lookup IOC, search runbook, explain log, summarize incident, search threat intel; write intents: create incident, block IP, isolate endpoint, add IOC, close incident)
- [ ] Confidence-aware cascade (lexical/IDF → semantic → hybrid → threshold → escalate/clarify)
- [ ] Tool definitions with schema, typed input, authz requirements, side-effect classification, idempotency behavior, audit event (`search_knowledge_base`, `search_sigma_rules`, `lookup_ioc`, `get_alert`, `get_incident`, `create_incident`, `block_ip`, `isolate_endpoint`)
- [ ] Mocked/local tool implementations

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

Phase 3 (hybrid retrieval) is functionally solid — RRF works and returns good results. Two things are worth closing out before moving on, because later phases build on top of them:

1. **Add `doc_type` + `metadata` to the document schema now** (Phase 1 gap). Runbooks and alerts (Phase 1, still unbuilt) will be new `doc_type`s, and source-filtered retrieval (Phase 3 gap) and citation formatting (Phase 6) both key off it. Retrofitting this after more phases are built means touching the parsers, both indexers, and both retrievers all over again.
2. **Then move to Phase 4** (cross-encoder reranking + a real eval set) — the plan explicitly wants to *demonstrate* why hybrid retrieval + reranking beats either method alone, and doing this before generation exists means the retrieval story can be validated in isolation, with numbers, instead of being buried inside end-to-end demo output later.

After that, Phase 5 (intent router) is the natural entry point into the agentic half of the project — everything from Phase 6 onward depends on knowing whether a request is a read or a write.
