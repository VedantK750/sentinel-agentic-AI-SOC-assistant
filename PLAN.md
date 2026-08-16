# Sentinel AI --- Agentic SOC Assistant

## 1. Project Goal

Build a security-focused Agentic RAG assistant that helps SOC analysts
investigate alerts, search security knowledge, query security data, and
execute a small set of approved remediation actions safely.

The system should demonstrate:

-   Hybrid retrieval
-   Semantic search
-   Lexical search
-   RRF fusion
-   Cross-encoder reranking
-   Citation-grounded generation
-   Groundedness verification
-   Intent classification and routing
-   Tool calling
-   RBAC
-   Propose-confirm-execute workflows
-   Idempotent actions
-   Audit logging
-   Fail-closed security controls
-   FastAPI backend
-   Persistent databases
-   CI/CD and deployment

The goal is a complete, interview-ready system rather than a
production-scale SOC platform.

------------------------------------------------------------------------

# 2. Core User Experience

A SOC analyst should be able to ask questions such as:

-   "What is T1059?"
-   "How do attackers dump credentials from LSASS?"
-   "How can I detect suspicious PowerShell?"
-   "Investigate this alert."
-   "What does this IP indicate?"
-   "Show me the relevant detection rules."
-   "Create an incident for this alert."
-   "Block this malicious IP."

Read operations should retrieve evidence and produce grounded answers.

Write operations should never execute immediately. They should first
produce a proposed action, require explicit confirmation, enforce
authorization, execute safely, and create an audit record.

------------------------------------------------------------------------

# 3. System Architecture

``` text
                         ┌─────────────────┐
                         │      User       │
                         └────────┬────────┘
                                  │
                                  ▼
                         ┌─────────────────┐
                         │   FastAPI API   │
                         └────────┬────────┘
                                  │
                                  ▼
                     ┌────────────────────────┐
                     │ Intent / Query Router  │
                     └───────────┬────────────┘
                                 │
                    ┌────────────┴────────────┐
                    │                         │
                  READ                      WRITE
                    │                         │
                    ▼                         ▼
          ┌───────────────────┐      ┌──────────────────┐
          │ Hybrid Retrieval  │      │ Action Planner   │
          │                   │      └────────┬─────────┘
          │ Qdrant + BM25     │               │
          │       ↓           │               ▼
          │      RRF          │      ┌──────────────────┐
          │       ↓           │      │ RBAC / Guardrails│
          │ Cross Encoder     │      └────────┬─────────┘
          └────────┬──────────┘               │
                   │                          ▼
                   ▼                    ┌───────────────┐
          ┌───────────────────┐         │ Confirmation  │
          │ LLM Generation    │         └───────┬───────┘
          └────────┬──────────┘                 │
                   │                            ▼
                   ▼                     ┌──────────────┐
          ┌───────────────────┐          │ Tool/API     │
          │ Groundedness Judge│          │ Execution    │
          └────────┬──────────┘          └──────┬───────┘
                   │                            │
                   ▼                            ▼
               Response                  Audit Logging
```

------------------------------------------------------------------------

# 4. Knowledge Base and Data Ingestion

## 4.1 MITRE ATT&CK

Use the official machine-readable MITRE ATT&CK STIX data.

Extract relevant `attack-pattern` objects and normalize them into the
internal document schema.

Required fields:

``` json
{
  "id": "T1059",
  "title": "Command and Scripting Interpreter",
  "content": "...",
  "source": "MITRE",
  "doc_type": "attack-technique"
}
```

Include useful metadata such as:

-   ATT&CK technique ID
-   tactic
-   sub-technique relationship
-   source URL where available

------------------------------------------------------------------------

## 4.2 Sigma Rules

Use the official Sigma rule repository and parse rules with the Sigma
ecosystem/pySigma where practical.

Normalize rules into the same document representation.

Example:

``` json
{
  "id": "...",
  "title": "Suspicious PowerShell Execution",
  "content": "...",
  "source": "Sigma",
  "doc_type": "detection-rule"
}
```

Useful fields:

-   rule ID
-   title
-   description
-   log source
-   detection logic
-   tags
-   ATT&CK mappings

------------------------------------------------------------------------

## 4.3 Security Runbooks

Create a small internal-style runbook corpus to simulate
organization-specific documentation.

Initial runbooks:

-   PowerShell investigation
-   Credential dumping investigation
-   Phishing investigation
-   Suspicious login investigation
-   Malware investigation
-   Ransomware investigation
-   Endpoint isolation procedure
-   Malicious IP response
-   Incident escalation procedure

These should be Markdown documents.

------------------------------------------------------------------------

## 4.4 Alert / Event Data

Create or use a small synthetic security event corpus.

Examples:

-   Windows process creation events
-   Windows authentication failures
-   Sysmon events
-   Suricata alerts
-   Suspicious PowerShell alerts
-   Malware alerts

This data will later support investigation workflows and tool calls.

------------------------------------------------------------------------

# 5. Document Normalization

Create one canonical internal document format regardless of the original
source.

Example:

``` json
{
  "id": "unique-id",
  "title": "Document title",
  "content": "Searchable document text",
  "source": "MITRE",
  "doc_type": "attack-technique",
  "metadata": {}
}
```

The retrieval layer must not care whether a document came from MITRE,
Sigma, a runbook, or another source.

------------------------------------------------------------------------

# 6. Indexing Pipeline

Build an offline indexing pipeline that:

1.  Loads normalized documents.
2.  Cleans and normalizes text.
3.  Generates embeddings.
4.  Stores embeddings and metadata in Qdrant.
5.  Tokenizes documents for lexical search.
6.  Builds the BM25 index.
7.  Persists the BM25 index and metadata.
8.  Records corpus/index version information.

The indexing process should be reproducible.

A future dataset update should be able to rebuild the indexes without
changing retrieval code.

------------------------------------------------------------------------

# 7. Dense Retrieval --- Qdrant

Use a sentence-transformer embedding model.

Initial model:

``` text
BAAI/bge-small-en-v1.5
```

Store:

-   embedding vector
-   document ID
-   title
-   content
-   source
-   doc type
-   useful metadata

Implement:

``` text
query → embedding → Qdrant nearest-neighbor search
```

Return a configurable number of candidates, initially around 10--20.

Support metadata filtering where useful.

Examples:

-   only MITRE documents
-   only Sigma rules
-   only runbooks

------------------------------------------------------------------------

# 8. Lexical Retrieval --- BM25

Use BM25 for exact keyword and identifier retrieval.

Important use cases:

-   T1059
-   T1003.001
-   CVE identifiers
-   IP addresses
-   process names
-   executable names
-   Sigma rule IDs
-   malware names
-   exact security terminology

Build and persist the BM25 index.

Return:

``` text
document_id
rank
BM25 score
```

Keep BM25 and Qdrant retrieval independently testable.

------------------------------------------------------------------------

# 9. Hybrid Retrieval

Implement independent retrieval from:

``` text
BM25
Qdrant
```

Then combine their result lists with Reciprocal Rank Fusion.

RRF should:

-   ignore incomparable raw scores
-   use rank positions
-   combine evidence from both retrievers
-   return a unified ranking

Initial formula:

``` text
RRF(doc) = Σ 1 / (k + rank)
```

Use a configurable `k`, initially 60.

The result should contain:

-   document ID
-   BM25 rank if present
-   dense rank if present
-   RRF score
-   source metadata

------------------------------------------------------------------------

# 10. Cross-Encoder Reranking

After RRF, rerank the top candidate set with a cross-encoder.

Pipeline:

``` text
BM25
   \
    → RRF → Top candidates → Cross Encoder → Final ranking
   /
Qdrant
```

The cross-encoder should receive:

``` text
query + document
```

and produce a relevance score.

Only rerank a limited candidate set to keep latency reasonable.

Expose:

-   initial rank
-   reranker score
-   final rank

This will make retrieval explainable during debugging.

------------------------------------------------------------------------

# 11. Retrieval Evaluation

Create a small fixed evaluation set.

Example queries:

``` text
T1059
credential dumping
powershell execution
curl file upload
mimikatz
ransomware
phishing
lsass
disable defender
reverse shell
```

For each query compare:

1.  Qdrant only
2.  BM25 only
3.  RRF hybrid
4.  RRF + cross-encoder

Track simple retrieval metrics such as:

-   Recall@K
-   Hit@K
-   MRR where appropriate

Also keep qualitative examples where one retriever succeeds and the
other fails.

The project should be able to demonstrate why hybrid retrieval was
chosen.

------------------------------------------------------------------------

# 12. Intent Resolution

Build a security-specific intent router.

Initial intents should include:

### Read intents

-   explain technique
-   search detection rule
-   investigate alert
-   lookup IOC
-   search runbook
-   explain log
-   summarize incident
-   search threat intelligence

### Write intents

-   create incident
-   block IP
-   isolate endpoint
-   add IOC
-   close incident

Start with a smaller set and make the architecture extensible toward 20+
intents.

The router should use a confidence-aware cascade:

``` text
Lexical / IDF signal
        ↓
Semantic similarity
        ↓
Hybrid fusion
        ↓
Confidence threshold
        ↓
Escalate / clarify when uncertain
```

The system must not guess a dangerous intent when confidence is low.

------------------------------------------------------------------------

# 13. Agent / Tool Layer

Define tools with explicit schemas.

Initial tools:

``` text
search_knowledge_base
search_sigma_rules
lookup_ioc
get_alert
get_incident
create_incident
block_ip
isolate_endpoint
```

Start with mocked/local implementations.

Each tool should have:

-   name
-   description
-   typed input
-   authorization requirements
-   side-effect classification
-   idempotency behavior
-   audit event

------------------------------------------------------------------------

# 14. Read Workflows

Implement read-only workflows first.

Example:

``` text
User:
"How do attackers dump credentials from LSASS?"

→ Intent classification
→ Hybrid retrieval
→ Reranking
→ LLM generation
→ Groundedness check
→ Answer with citations
```

Another:

``` text
User:
"How do I detect suspicious PowerShell?"

→ Intent classification
→ Sigma retrieval
→ Reranking
→ Grounded answer
→ Sigma citations
```

------------------------------------------------------------------------

# 15. Citation-Grounded Generation

The LLM should receive only the selected evidence plus the user query.

The generation prompt should require:

-   answer only from provided evidence
-   clearly distinguish evidence from inference
-   cite supporting documents
-   state when evidence is insufficient
-   never fabricate a source

Citation format should identify the source document and relevant
metadata.

Example:

``` text
[T1059] MITRE ATT&CK
[Sigma: <rule-id>] Suspicious PowerShell Execution
```

------------------------------------------------------------------------

# 16. Groundedness Judge

Add a post-generation verification step.

Pipeline:

``` text
Retrieved evidence
        +
Generated answer
        ↓
Groundedness Judge
        ↓
Supported?
   /          \
 Yes           No
 ↓             ↓
Return       Reject / regenerate
```

The judge should check whether important claims in the answer are
supported by retrieved evidence.

If the answer is not sufficiently grounded:

-   regenerate with stricter instructions, or
-   return an evidence-insufficient response.

------------------------------------------------------------------------

# 17. Security and RBAC

Implement role-based access control.

Initial roles:

``` text
analyst
senior_analyst
admin
```

Define permissions such as:

``` text
knowledge.read
alerts.read
incidents.read
incidents.create
network.block_ip
endpoint.isolate
```

Every tool call must pass an authorization check.

------------------------------------------------------------------------

# 18. Fail-Closed Guardrails

Security-sensitive operations must fail closed.

Examples:

-   authorization service unavailable → deny
-   missing user identity → deny
-   missing required permission → deny
-   malformed action request → deny
-   missing confirmation → deny
-   unknown tool → deny
-   invalid target → deny

Never silently fall back to allowing a dangerous operation.

------------------------------------------------------------------------

# 19. Propose → Confirm → Execute

Every write action follows this workflow:

``` text
User request
     ↓
Intent detection
     ↓
Authorization
     ↓
Action proposal
     ↓
User confirmation
     ↓
Re-check authorization
     ↓
Idempotency check
     ↓
Execute
     ↓
Audit
```

Example:

``` text
Proposed action:

Block IP: 185.x.x.x
Reason: malicious IOC
Target: corporate firewall

Confirm?
```

Only explicit confirmation allows execution.

------------------------------------------------------------------------

# 20. Mock Security APIs

Do not depend on a real firewall or EDR.

Implement local mock services for:

### Firewall

``` text
block_ip(ip)
unblock_ip(ip)
```

### EDR

``` text
isolate_endpoint(host)
release_endpoint(host)
```

### Incident system

``` text
create_incident(...)
update_incident(...)
```

The purpose is to demonstrate agentic execution safely.

------------------------------------------------------------------------

# 21. Idempotency

Write operations must not accidentally execute twice.

Example:

``` text
block_ip(1.2.3.4)
```

If the same request is submitted again with the same idempotency key:

``` text
do not create a second action
return the original result
```

Store idempotency records in PostgreSQL.

------------------------------------------------------------------------

# 22. Audit Logging

Every security-sensitive operation should produce an immutable-style
audit event.

Record:

``` text
timestamp
user_id
role
intent
tool
action
target
authorization result
confirmation
execution result
idempotency key
request ID
```

Example:

``` json
{
  "user": "analyst-01",
  "action": "block_ip",
  "target": "185.x.x.x",
  "authorized": true,
  "confirmed": true,
  "result": "success"
}
```

------------------------------------------------------------------------

# 23. PostgreSQL

Use PostgreSQL for application state that needs relational consistency.

Store:

-   users
-   roles
-   permissions
-   incidents
-   actions
-   confirmations
-   idempotency keys
-   audit events

Do not use PostgreSQL as a replacement for Qdrant or BM25.

Each storage system should have a clear responsibility.

------------------------------------------------------------------------

# 24. API Layer --- FastAPI

Create clean REST endpoints.

Initial endpoints:

``` text
POST /chat
POST /search
POST /intent
POST /actions/propose
POST /actions/{id}/confirm

GET /alerts/{id}
GET /incidents/{id}
GET /audit
```

Use Pydantic schemas for every request and response.

------------------------------------------------------------------------

# 25. Conversation / Agent State

Maintain enough state to support:

``` text
proposal → confirmation → execution
```

The system must know:

-   which user proposed the action
-   what action was proposed
-   target
-   authorization result
-   confirmation status
-   expiration
-   idempotency key

A confirmation should not be reusable indefinitely.

------------------------------------------------------------------------

# 26. Frontend

Build a simple React interface.

It only needs to demonstrate:

### Chat

``` text
User question
Assistant answer
Citations
```

### Retrieval evidence

Show:

-   source
-   document
-   relevance score
-   citations

### Action proposal

Show:

``` text
ACTION PROPOSED

Block IP: 1.2.3.4

[Confirm] [Reject]
```

### Audit

Show recent actions.

Do not spend time making the UI visually elaborate.

------------------------------------------------------------------------

# 27. Observability

Add basic structured logging.

Every request should have a request ID.

Log:

-   intent
-   retrieval latency
-   BM25 latency
-   Qdrant latency
-   RRF latency
-   reranker latency
-   LLM latency
-   tool execution latency
-   final outcome

This makes the project feel like a real backend system and makes
debugging easier.

------------------------------------------------------------------------

# 28. Testing

Implement tests for the important failure modes.

## Retrieval

-   exact technique lookup
-   semantic query
-   Sigma lookup
-   empty results
-   mixed-source results

## Intent

-   known intent
-   ambiguous intent
-   low-confidence intent
-   dangerous write intent

## Authorization

-   permitted action
-   denied action
-   missing role
-   missing permission
-   authorization service failure

## Confirmation

-   confirmed action
-   rejected action
-   expired confirmation
-   missing confirmation

## Idempotency

-   repeated request
-   duplicate confirmation
-   retry after timeout

## Grounding

-   supported answer
-   unsupported claim
-   no evidence

------------------------------------------------------------------------

# 29. CI/CD

Set up GitHub Actions for:

``` text
lint
unit tests
integration tests
type checks
build
```

The pipeline should fail when tests fail.

Keep configuration in environment variables.

Never commit:

-   API keys
-   passwords
-   tokens
-   private credentials

------------------------------------------------------------------------

# 30. Docker / Deployment

Containerize the backend.

Services can be:

``` text
FastAPI
PostgreSQL
Qdrant
Frontend
```

Use Docker Compose for local development.

The deployment should allow the entire application to be started with
one command.

------------------------------------------------------------------------

# 31. Security Hardening

Before calling the project complete:

-   validate all tool inputs
-   sanitize user-controlled identifiers
-   enforce authorization server-side
-   never trust frontend permissions
-   require confirmation for writes
-   use short-lived confirmation tokens
-   prevent arbitrary tool invocation
-   restrict tool schemas
-   redact sensitive data
-   avoid logging secrets
-   fail closed
-   add request timeouts
-   handle LLM/tool failures safely

------------------------------------------------------------------------

# 32. Final Demo Scenario

The final demo should tell one coherent story.

## Scenario

An analyst receives a suspicious PowerShell alert.

### Step 1

User:

``` text
Investigate alert A-1042.
```

Assistant:

-   retrieves alert
-   identifies suspicious PowerShell
-   retrieves MITRE technique
-   retrieves Sigma detection rules
-   retrieves investigation runbook
-   produces cited explanation

### Step 2

User:

``` text
Should we block the source IP?
```

Assistant:

-   looks up IOC
-   explains evidence
-   proposes blocking the IP

### Step 3

Assistant:

``` text
Proposed action:

Block 185.x.x.x on corporate firewall.

Reason:
The IP is associated with the investigated alert.

Confirm?
```

### Step 4

User:

``` text
Confirm.
```

System:

``` text
RBAC check
→ confirmation validation
→ idempotency check
→ mock firewall API
→ audit log
```

### Step 5

Assistant:

``` text
IP blocked successfully.

Audit ID: ...
```

This single scenario demonstrates most of the architecture.

------------------------------------------------------------------------

# 33. Final Repository Structure

``` text
sentinel-ai/

├── app/
│   ├── main.py
│   │
│   ├── api/
│   │   ├── chat.py
│   │   ├── search.py
│   │   ├── actions.py
│   │   └── incidents.py
│   │
│   ├── retrieval/
│   │   ├── qdrant.py
│   │   ├── bm25.py
│   │   ├── rrf.py
│   │   └── reranker.py
│   │
│   ├── agent/
│   │   ├── router.py
│   │   ├── planner.py
│   │   └── state.py
│   │
│   ├── generation/
│   │   ├── generator.py
│   │   ├── prompts.py
│   │   └── groundedness.py
│   │
│   ├── actions/
│   │   ├── firewall.py
│   │   ├── edr.py
│   │   └── incidents.py
│   │
│   ├── auth/
│   │   ├── rbac.py
│   │   └── policies.py
│   │
│   ├── database/
│   │   ├── models.py
│   │   └── session.py
│   │
│   └── audit/
│       └── logger.py
│
├── scripts/
│   ├── parse_mitre.py
│   ├── parse_sigma.py
│   ├── build_embeddings.py
│   ├── index_bm25.py
│   └── evaluate_retrieval.py
│
├── data/
│   ├── documents.json
│   ├── runbooks/
│   └── sample_alerts/
│
├── frontend/
│
├── tests/
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── PLAN.md
└── README.md
```

------------------------------------------------------------------------

# 34. Scope Control

The following are explicitly **out of scope** for the first complete
version:

-   real production firewall integration
-   real EDR integration
-   real SIEM deployment
-   autonomous destructive actions
-   multi-agent orchestration
-   Kubernetes deployment
-   distributed Qdrant cluster
-   fine-tuning an LLM
-   training a custom embedding model
-   building a custom BM25 implementation
-   massive-scale threat intelligence ingestion
-   elaborate frontend design

If a feature is not necessary to demonstrate the core architecture, put
it in a future-ideas list instead of expanding the scope.

------------------------------------------------------------------------

# 35. Definition of Done

The project is complete when all of the following work together:

``` text
User
 ↓
FastAPI
 ↓
Intent Router
 ↓
 ┌───────────────┬────────────────┐
 │               │
Read            Write
 │               │
 ↓               ↓
BM25 + Qdrant   Propose
 ↓               ↓
RRF             RBAC
 ↓               ↓
Cross Encoder   Confirm
 ↓               ↓
LLM             Idempotency
 ↓               ↓
Groundedness    Execute
 ↓               ↓
Citations       Audit
```

And the final demo can successfully show:

-   a semantic security question
-   an exact identifier lookup
-   hybrid retrieval
-   reranking
-   grounded citations
-   an investigation workflow
-   a proposed security action
-   permission enforcement
-   explicit confirmation
-   safe mock execution
-   idempotent retry behavior
-   audit logging

The project should be judged by **working behavior and engineering
decisions**, not by the number of technologies or features listed.
