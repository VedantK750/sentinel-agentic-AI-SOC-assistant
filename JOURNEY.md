# The Journey: Building Hybrid Retrieval for Sentinel AI

A short, chronological account of how this project's retrieval system was built — what we built, what broke, and how we knew it was actually fixed. Written to be told out loud.

---

## Starting point

A security RAG system over MITRE ATT&CK (858 techniques) and SigmaHQ detection rules (3,137 rules), 3,995 documents total. Two indices already existed — a BM25 lexical index and a Qdrant vector index — but nothing combined them, there was no way to measure retrieval quality, and the repo wasn't even under version control.

---

## 1. Hybrid retrieval: implementing RRF

**What:** Combined the BM25 and vector retrievers using Reciprocal Rank Fusion — `score(doc) = Σ 1/(k + rank)` across each retriever's ranked list, `k=60`.

**Why RRF specifically:** BM25 scores (unbounded term-frequency) and cosine similarity (0–1) live on incompatible scales. Blending them with weights requires constant recalibration as the corpus changes. RRF sidesteps this entirely by only looking at *rank position*, never the raw score.

Also set up git for the first time, and started two living documents that got used for the rest of the project: `DECISIONS.md` (why, not just what) and `ARCHITECTURE.md` (how data flows).

---

## 2. Proving it actually mattered: reranking + a real eval

Built a fixed 10-query eval set (`T1059`, `mimikatz`, `ransomware`, etc.) and measured **Hit@K, Recall@K, and MRR** — not vibes. Added a cross-encoder reranker (`ms-marco-MiniLM-L-6-v2`) on top of RRF.

**The number that mattered most:** for the query `"T1059"`, vector-only search scored **0.00 on every metric.** Pure semantic search completely missed an exact-identifier lookup. This wasn't a hypothetical — it was measured proof that hybrid retrieval wasn't a nice-to-have, it was fixing a real blind spot.

| method | Hit@10 | Recall@10 | MRR |
|---|---|---|---|
| BM25 only | 1.000 | 0.645 | 1.000 |
| Vector only | 0.900 | 0.494 | 0.764 |
| RRF | 1.000 | 0.645 | 0.933 |
| RRF + rerank | 1.000 | 0.682 | 1.000 |

---

## 3. Fixing the data model before building on top of it

The document schema was flat — `{id, title, content, source}` — and it was quietly throwing away structure that already existed in the raw data: MITRE's `kill_chain_phases` (the tactic) and Sigma's `tags` (the mapping back to an ATT&CK technique ID) were both sitting unparsed inside blobs of text.

Refactored every document to `{document_id, doc_type, source, title, content, metadata}`, rewrote both parsers to actually extract that structure, and rebuilt both indices.

**How we knew it didn't break anything:** reran every existing smoke test and the full eval suite — scores and rankings came back numerically identical. A schema change with zero behavioral change, proven, not assumed.

**Added a validator** (`scripts/validate_documents.py`) that checks extraction is actually working: **100% of MITRE docs have tactics, 89% of Sigma rules have ATT&CK technique mappings.**

---

## 4. Intent routing + a tool layer

Built a router that classifies a query (`"What is T1059?"`, `"block this IP"`) into an intent, using the same lexical+semantic combination as retrieval — a keyword/regex signal plus embedding similarity against example phrasings, gated by a confidence threshold that's **stricter for write actions than read actions** (fail closed: don't guess your way into proposing a firewall change).

Backed it with a tool registry — real tools for search (backed by the full retrieval pipeline), honest stubs for anything needing infrastructure that doesn't exist yet (no RBAC, no incident database, so `block_ip` reports "classified correctly, not executed" instead of pretending to do something).

---

## 5. Bug #1: BM25 was silently punishing plain English

**The trigger:** the very first natural-language sentence ever run through the router — `"What is T1059?"` — returned a completely unrelated document instead of T1059 itself.

**Root cause:** classic Okapi BM25's IDF formula goes *negative* for any word appearing in more than half the corpus. "is" and "what" appear in nearly every technique description, so they weren't just unhelpful — they were **actively subtracting score** from documents that used them a lot, which is most fluently-written English. One correct term (`t1059`) wasn't enough to outweigh two actively penalizing ones.

**Why it took this long to find:** every single query used anywhere in the project up to that point — the eval set, every demo — was a short keyword phrase (`"curl file upload"`, `"T1059"`). None of them had stopwords. The bug had been sitting in the tokenizer since Phase 2, invisible until the first real sentence hit it.

**Fix:** filter stopwords at tokenization, and collapse two duplicate copies of `tokenize()` into one shared function (index-time and query-time tokenization must never drift apart — that's exactly the kind of thing that lets a bug like this hide).

**Verified:** reran the full eval — numbers flat-to-slightly-improved, confirmed nothing regressed.

---

## 6. Bug #2: RRF can't tell "confident" from "lucky"

Even after the stopword fix, that same query still didn't put T1059 at rank 1 through the full pipeline. Here's the actual mechanism:

RRF only ever looks at rank position, never the score. So it can't distinguish "BM25 rank #1 because this is a near-unique exact token match" from "BM25 rank #1 because it edged out rank #2 by a hair." A document ranked *moderately* by **both** retrievers can out-score a document ranked **#1 by only one** — that's RRF's whole design (reward combined evidence), just backfiring on an exact-ID query where one retriever's signal should have been decisive on its own.

**What we didn't do:** just lower `k` to make rank-1 dominate more. That's a global change — it would've altered behavior for every query in the eval set, including all the ones where RRF's "combine evidence across retrievers" behavior was already correct. Fixing a specific, diagnosable case by tuning a global parameter blindly is how you trade one bug for a different regression.

**What we did instead:** built `ExactMatchBooster` — detect known-item identifiers in the query (technique IDs, Sigma rule UUIDs) via regex, and if the corpus has an exact match, pin it to the front of the results, as an explicit final stage on top of the existing pipeline (not folded into RRF or the reranker, so their own validated behavior stays intact and measurable).

**Measured, not assumed:** added a query built specifically to stress-test this — `"What is T1003.001?"` — and ran it through every method:

| method | Hit@10 | Recall@10 | MRR |
|---|---|---|---|
| RRF + rerank | **0.00** | **0.00** | **0.00** |
| RRF + rerank + boost | 1.00 | 1.00 | 1.00 |

RRF+rerank didn't just under-rank the right answer — it pushed it **completely out of the top 10.** The fix took it to a perfect score, and the aggregate across the whole eval set improved too (Hit@10 1.000, Recall@10 0.715, MRR 1.000, up from 0.909/0.625/0.909) — not just a patch for one cherry-picked query.

---

## Where this leaves us

```
query → BM25 + vector search → RRF fusion → cross-encoder rerank → exact-match boost → result
                                                                            ↓
                                                     intent router → tool layer (read/write)
```

Every stage is independently runnable and independently measured — none of it is "trust me, it works."

## The talking points

- **Hybrid retrieval isn't a checkbox** — vector-only search scored a literal 0.00 on an exact-ID query. That's not a style preference, it's a measured blind spot.
- **Know your algorithm's actual tradeoff, not just its benefit.** RRF avoids score-comparability problems *by design* — and that same design choice is exactly why it can't recognize an unusually confident single-retriever match. Both are consequences of the same decision.
- **Bugs hide in untested input shapes.** The BM25 stopword bug existed since Phase 2 but only a full natural-language sentence could trigger it — every prior query happened to be short keyword phrases.
- **Fix the mechanism, not the symptom.** Retuning `k` would have "fixed" the visible symptom while quietly changing every other query's behavior. Diagnosing the actual cause (rank-only fusion can't see confidence) led to a fix that only activates for the specific case it's meant for.
- **Never ship a fix on faith.** Every change in this project — schema refactor, tokenizer fix, boosting — was checked against the same eval suite before moving on. "It looks right" and "it measurably didn't regress" are different claims.
