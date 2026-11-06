"""LLM-as-judge alternative to the local NLI groundedness judge (groundedness.py).
Same verify(answer) interface (drop-in for GenerationPipeline), different backend:
an instruction-following LLM instead of a local cross-encoder classifier.

Two design choices worth calling out, both driven by known LLM-as-judge failure
modes rather than assumed:

1. No self-reported numeric confidence. LLM-reported probabilities/confidence
   scores are known to be poorly calibrated -- they cluster around round numbers
   (70%, 90%, 95%) regardless of true certainty, unlike a real classifier's
   softmax. Asking for one here would just be manufacturing a fake-precise number.
   Instead the prompt asks for a categorical verdict plus a one-sentence
   justification citing the evidence -- more reliable to parse, and the reason
   text is more useful for debugging a wrong verdict than an uncalibrated float
   would have been anyway.

2. All claims for one answer are verified in a SINGLE LLM call, not one call per
   claim. This is the opposite conclusion from the local NLI judge's batching
   experiment (see DECISIONS.md) -- there, batching didn't help because the local
   model was CPU-compute-bound, and combining calls doesn't reduce total compute.
   A remote LLM API is the opposite: network/queueing round-trip time is a large,
   roughly fixed-per-call cost (observed elsewhere in this project at 6-90s per
   call), so collapsing N claims into 1 round trip instead of N is a real win
   here specifically, not a copy-paste of a fix that already failed once.

See DECISIONS.md for the measured accuracy/latency comparison against the NLI judge.
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

from app.retrieval.documents import DOCS_PATH, load_content_by_id

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(dotenv_path=ROOT / ".env")

# A separate, deliberately small/cheap model from generation's LLM_MODEL -- judging
# is a narrower, more constrained task (read evidence + claim, classify) than
# open-ended answer generation, so it doesn't need the same model. Picked from the
# configured endpoint's live catalog: non-thinking, ~$0.05/M input tokens (cost is
# a non-issue at this scale), and known-good at structured instruction-following.
JUDGE_MODEL = os.environ.get("LLM_JUDGE_MODEL", "mistralai/mistral-small-24b-instruct-2501")
REQUEST_TIMEOUT = 60.0

JUDGE_SYSTEM_PROMPT = """You are a strict fact-checking judge. You will be given a numbered list of EVIDENCE/CLAIM pairs. For EACH pair, decide whether the evidence actually supports the claim.

A claim is "supported" only if the evidence directly states or clearly implies the claim's content. Mark a claim "not_supported" in each of these cases, even if the claim is true in general knowledge:
- HALLUCINATION: the claim states something not present anywhere in its evidence.
- MISATTRIBUTION: the claim is a true fact, but THIS SPECIFIC evidence does not say it -- e.g. the evidence is about a related but different topic, or a different sub-technique.
- OVERREACH: the claim is a plausible-sounding inference, generalization, or judgment call that goes beyond what the evidence literally states.

Respond with ONLY a JSON object of this exact shape, with exactly one verdict per numbered pair, in order:
{"verdicts": [{"index": 1, "verdict": "supported", "reason": "one sentence citing the specific evidence text, or explaining why it's absent"}, ...]}"""


def _build_batch_prompt(pairs):
    blocks = [f"### Pair {i}\nEVIDENCE:\n{evidence}\n\nCLAIM:\n{claim}" for i, (evidence, claim) in enumerate(pairs, 1)]
    return "\n\n".join(blocks)


class LLMGroundednessJudge:
    """Drop-in alternative to GroundednessJudge -- same verify(answer) -> {"grounded",
    "claim_results"} interface, so GenerationPipeline can use either without change.
    claim_results here carry "reason" (the judge's justification) instead of
    "entailment_prob" (no real probability exists for an LLM-judge verdict).
    """

    def __init__(self, model=JUDGE_MODEL, docs_path=DOCS_PATH, timeout=REQUEST_TIMEOUT):
        self.client = OpenAI(
            api_key=os.environ["LLM_API_KEY"],
            base_url=os.environ["LLM_ENDPOINT"],
            timeout=timeout,
        )
        self.model = model
        self.content_by_id = load_content_by_id(docs_path)

    def _evidence_text(self, cited_document_ids):
        return " ".join(self.content_by_id.get(doc_id, "") for doc_id in cited_document_ids).strip()

    def _judge_batch(self, pairs):
        """pairs: list of (evidence_text, claim_text). Returns a list of
        {"supported": bool, "reason": str}, same length and order as `pairs`.
        On any failure (API error, unparseable/incomplete response), every pair in
        the batch is marked unsupported -- fail closed, consistent with the NLI
        judge's posture, never silently pass a claim the judge couldn't actually
        evaluate.
        """
        messages = [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": _build_batch_prompt(pairs)},
        ]
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                response_format={"type": "json_object"},
                max_tokens=150 * len(pairs) + 200,
            )
        except OpenAIError as e:
            return [{"supported": False, "reason": f"judge call failed: {e!r}"} for _ in pairs]

        try:
            parsed = json.loads(response.choices[0].message.content)
            by_index = {v["index"]: v for v in parsed["verdicts"]}
        except (json.JSONDecodeError, TypeError, KeyError, AttributeError):
            return [{"supported": False, "reason": "judge response unparseable"} for _ in pairs]

        results = []
        for i in range(len(pairs)):
            v = by_index.get(i + 1)
            if v is None:
                results.append({"supported": False, "reason": "judge omitted a verdict for this pair"})
            else:
                results.append({"supported": v.get("verdict") == "supported", "reason": v.get("reason", "")})
        return results

    def verify(self, answer):
        """Returns {"grounded": bool, "claim_results": [...]}. An answer with zero
        claims is not grounded. Claims citing a document_id with no evidence text
        (fabricated citation) are unsupported by construction and skip the LLM call
        entirely, same short-circuit as the NLI judge.
        """
        claims = answer.claims
        results = [None] * len(claims)
        batch_indices, pairs = [], []

        for i, claim in enumerate(claims):
            evidence_text = self._evidence_text(claim.cited_document_ids)
            if not evidence_text:
                results[i] = {"claim": claim, "supported": False, "reason": "cited document not found"}
            else:
                batch_indices.append(i)
                pairs.append((evidence_text, claim.text))

        if pairs:
            verdicts = self._judge_batch(pairs)
            for idx, v in zip(batch_indices, verdicts):
                results[idx] = {"claim": claims[idx], "supported": v["supported"], "reason": v["reason"]}

        grounded = bool(results) and all(r["supported"] for r in results)
        return {"grounded": grounded, "claim_results": results}


def main():
    judge = LLMGroundednessJudge()

    class _Claim:
        def __init__(self, text, cited_document_ids):
            self.text = text
            self.cited_document_ids = cited_document_ids

    class _Answer:
        def __init__(self, claims):
            self.claims = claims

    cases = [
        _Claim("T1059 covers abuse of command and scripting interpreters to execute commands or scripts.", ["mitre_attack:T1059"]),
        _Claim("T1059 specifically refers to the use of PowerShell for credential dumping.", ["mitre_attack:T1059"]),
        _Claim("T1059 was first documented in 1998.", ["mitre_attack:T9999-does-not-exist"]),
    ]
    result = judge.verify(_Answer(cases))
    print(f"grounded={result['grounded']}\n")
    for r in result["claim_results"]:
        print(f"  supported={r['supported']}  reason={r['reason']!r}  {r['claim'].text}")


if __name__ == "__main__":
    main()
