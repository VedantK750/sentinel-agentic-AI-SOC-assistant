from .generator import Generator
from .groundedness import GroundednessJudge

MAX_RETRIES = 1


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
    """

    def __init__(self, generator=None, judge=None):
        self.generator = generator or Generator()
        self.judge = judge or GroundednessJudge()

    def answer(self, query, documents):
        failed_claims = None
        accumulated = []
        seen_texts = set()

        def merge_supported(claim_results):
            for r in claim_results:
                if r["supported"] and r["claim"].text not in seen_texts:
                    accumulated.append(r["claim"].model_dump())
                    seen_texts.add(r["claim"].text)

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
