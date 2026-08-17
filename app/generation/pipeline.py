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
    """

    def __init__(self, generator=None, judge=None):
        self.generator = generator or Generator()
        self.judge = judge or GroundednessJudge()

    def answer(self, query, documents):
        failed_claims = None
        verdict = None

        for attempt in range(1, MAX_RETRIES + 2):
            print(f"[pipeline] generation attempt {attempt}/{MAX_RETRIES + 1}...")
            generated = self.generator.generate(query, documents, failed_claims=failed_claims)
            if generated is None:
                continue  # unparseable response -- retry blind, nothing to point at

            if not generated.claims:
                # Model correctly declined (insufficient evidence) -- nothing to verify,
                # nothing to retry. This is success, not failure.
                return {
                    "claims": [],
                    "grounded": True,
                    "insufficient_evidence": generated.insufficient_evidence,
                    "attempts": attempt,
                }

            print(f"[pipeline] verifying {len(generated.claims)} claim(s) against evidence...")
            verdict = self.judge.verify(generated)
            if verdict["grounded"]:
                return {
                    "claims": [c.model_dump() for c in generated.claims],
                    "grounded": True,
                    "insufficient_evidence": generated.insufficient_evidence,
                    "attempts": attempt,
                }

            failed_claims = [
                (r["claim"].text, r["claim"].cited_document_ids)
                for r in verdict["claim_results"]
                if not r["supported"]
            ]

        supported_claims = (
            [r["claim"].model_dump() for r in verdict["claim_results"] if r["supported"]]
            if verdict
            else []
        )
        return {
            "claims": supported_claims,
            "grounded": False,
            "insufficient_evidence": True,
            "attempts": MAX_RETRIES + 1,
            "message": (
                "Some claims could not be verified against the evidence and were dropped."
                if supported_claims
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
