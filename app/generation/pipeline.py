import numpy as np
from sentence_transformers import SentenceTransformer

from .generator import Generator
from .groundedness import GroundednessJudge

MAX_RETRIES = 1

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"  # same model already used for retrieval/routing

# Claims are deduplicated across generation attempts by semantic similarity, not exact
# text match -- a regeneration can rephrase a claim just enough to dodge a naive string
# comparison (different quote style, an inserted parenthetical) while stating the exact
# same fact. Found on a real answer: the same source sentence survived two attempts as
# two "different" claims, once quoted with 'single quotes' and once with "double quotes".
# Threshold picked empirically, not guessed: known duplicate pairs from that answer
# scored 0.984-0.998 cosine similarity; genuinely distinct claims from the same answer
# scored 0.31-0.52. 0.90 sits with wide margin on both sides. See DECISIONS.md.
DEDUP_SIMILARITY_THRESHOLD = 0.90


def _cosine_similarity(a, b):
    a_norm = a / np.linalg.norm(a, axis=1, keepdims=True)
    b_norm = b / np.linalg.norm(b, axis=1, keepdims=True)
    return a_norm @ b_norm.T


class GenerationPipeline:
    """Ties generation (§14/§15) and the groundedness judge (§16) together, including
    the regen-or-reject path: on an ungrounded answer, retry once naming exactly which
    claims failed; if it's still ungrounded, fall back to only the claims that DID
    verify, with an explicit "insufficient evidence" note -- never silently return an
    answer that failed the check. See the groundedness-judge design discussion in
    DECISIONS.md for why this is one retry, not a loop.

    Verified claims are accumulated across attempts, not replaced each retry. Found
    the hard way: each retry is a full regeneration, not a patch of the specific
    failed claim, and the model can rephrase a claim that passed fine into wording
    that fails the judge (or vice versa) even though the underlying fact is
    unchanged -- observed directly on a real query, where a `doas` tool claim scored
    0.851 (pass) in one attempt and 0.125 (fail) in the next, just from being
    reworded shorter. Keeping only the *last* attempt's survivors meant a handful of
    already-verified, still-true claims from an earlier attempt got silently thrown
    away for no reason connected to their truth. See DECISIONS.md.

    That same "a retry can reword a claim" behavior also means the SAME fact can
    survive both attempts under slightly different wording -- accumulation alone
    would then show it to the user twice. Dedup here is by embedding cosine
    similarity (DEDUP_SIMILARITY_THRESHOLD), not exact string match, so a cosmetic
    reword doesn't slip past it. See DECISIONS.md.
    """

    def __init__(self, generator=None, judge=None, embedder=None):
        self.generator = generator or Generator()
        # NLI cross-encoder, not the LLM-as-judge alternative (llm_judge.py). The LLM
        # judge was tried and measured: 11x faster (one batched API call vs local
        # inference) but accuracy dropped from 100% to 72% on the same labeled set,
        # specifically failing on paraphrased-but-true claims -- it conflated
        # "restated in different words" with "not actually supported," the exact
        # failure mode this project has been trying to eliminate. Not an acceptable
        # trade for a safety-critical hallucination check. See DECISIONS.md.
        self.judge = judge or GroundednessJudge()
        self.embedder = embedder or SentenceTransformer(EMBEDDING_MODEL_NAME)

    def answer(self, query, documents):
        failed_claims = None
        accumulated = []
        accumulated_embeddings = None  # np.ndarray, grown as claims are accepted

        def merge_supported(claim_results):
            nonlocal accumulated_embeddings
            supported = [r for r in claim_results if r["supported"]]
            if not supported:
                return
            new_embeddings = self.embedder.encode([r["claim"].text for r in supported])
            for r, embedding in zip(supported, new_embeddings):
                embedding = embedding.reshape(1, -1)
                if accumulated_embeddings is not None:
                    max_sim = _cosine_similarity(embedding, accumulated_embeddings).max()
                    if max_sim >= DEDUP_SIMILARITY_THRESHOLD:
                        continue  # near-duplicate of an already-accumulated claim
                accumulated.append(r["claim"].model_dump())
                accumulated_embeddings = (
                    embedding if accumulated_embeddings is None
                    else np.vstack([accumulated_embeddings, embedding])
                )

        for attempt in range(1, MAX_RETRIES + 2):
            print(f"[pipeline] generation attempt {attempt}/{MAX_RETRIES + 1}...")
            generated = self.generator.generate(query, documents, failed_claims=failed_claims)
            if generated is None:
                continue  # unparseable response -- retry blind, nothing to point at

            if not generated.claims:
                # Model declined this attempt. If earlier attempts already verified
                # some claims, that's a real answer -- a later regeneration giving up
                # shouldn't erase it. Otherwise this is a clean, correct "insufficient
                # evidence" from the very first attempt.
                if accumulated:
                    break
                return {
                    "claims": [],
                    "grounded": True,
                    "insufficient_evidence": generated.insufficient_evidence,
                    "attempts": attempt,
                }

            print(f"[pipeline] verifying {len(generated.claims)} claim(s) against evidence...")
            verdict = self.judge.verify(generated)
            merge_supported(verdict["claim_results"])

            if verdict["grounded"]:
                return {
                    "claims": accumulated,
                    "grounded": True,
                    "insufficient_evidence": generated.insufficient_evidence,
                    "attempts": attempt,
                }

            failed_claims = [
                (r["claim"].text, r["claim"].cited_document_ids)
                for r in verdict["claim_results"]
                if not r["supported"]
            ]

        # `grounded` reflects whether `claims` is trustworthy, not whether every
        # attempt went cleanly -- every entry in `accumulated` individually passed
        # the judge, whichever attempt it came from, so this is grounded whenever
        # there's anything to show at all.
        return {
            "claims": accumulated,
            "grounded": bool(accumulated),
            "insufficient_evidence": not accumulated,
            "attempts": MAX_RETRIES + 1,
            "message": (
                "Answer assembled from claims verified across multiple generation "
                "attempts; some individual claims along the way were unsupported "
                "and dropped."
                if accumulated
                else "Could not produce a grounded answer from the retrieved evidence."
            ),
        }


def main():
    from app.agent.tools import build_default_registry
    from app.retrieval.documents import load_content_by_id

    registry = build_default_registry()
    pipeline = GenerationPipeline()
    content_by_id = load_content_by_id()

    queries = ["What is T1059?", "How do I detect mimikatz?", "What is the airspeed of a swallow?"]
    for query in queries:
        results = registry.call("search_knowledge_base", query=query, limit=3)["results"]
        evidence = [
            {"document_id": r["document_id"], "title": r["title"], "content": content_by_id[r["document_id"]]}
            for r in results
        ]
        result = pipeline.answer(query, evidence)
        print(f"\nquery: {query!r}")
        print(f"  grounded={result['grounded']}  insufficient_evidence={result['insufficient_evidence']}  attempts={result['attempts']}")
        if result.get("message"):
            print(f"  {result['message']}")
        for claim in result["claims"]:
            print(f"  - {claim['text']}  {claim['cited_document_ids']}")


if __name__ == "__main__":
    main()
