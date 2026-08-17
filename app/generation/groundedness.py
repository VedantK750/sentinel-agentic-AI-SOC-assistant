import numpy as np
from sentence_transformers import CrossEncoder

from app.retrieval.documents import DOCS_PATH, load_content_by_id

MODEL_NAME = "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli"

# This model's output is 3 logits over (entailment, neutral, contradiction) -- verified
# empirically, not assumed, via model.config.id2label and known entailed/contradicted/
# neutral pairs, since a wrong index silently inverts every verdict. Also verified
# empirically that this checkpoint specifically (trained on FEVER -- claim-vs-evidence
# fact verification, not just short generic sentence pairs like plain SNLI/MNLI
# checkpoints) is the one that actually works for long-document-premise vs short-claim
# entailment: a first attempt with cross-encoder/nli-deberta-v3-base scored an
# obviously-true, near-verbatim claim at entailment probability 0.003 -- unusable.
# See DECISIONS.md.
ENTAILMENT_INDEX = 0

# A claim counts as supported only if the evidence more-likely-than-not entails it --
# i.e. entailment must outweigh contradiction + neutral combined, not just edge them
# out individually. Deliberately strict: one unsupported claim fails the whole answer
# (see GroundednessJudge.verify), matching the same fail-closed posture as the intent
# router's confidence gate.
ENTAILMENT_THRESHOLD = 0.5


def _softmax(logits):
    exp = np.exp(logits - np.max(logits))
    return exp / exp.sum()


class GroundednessJudge:
    """Post-generation verification (PLAN §16): checks each claim in a GeneratedAnswer
    against only the document(s) it cites -- not the whole evidence pool -- using an
    NLI cross-encoder (premise = cited document's content, hypothesis = the claim).
    This catches three distinct failure modes: hallucination (no real support
    anywhere), misattribution (a claim citing a real, relevant document that doesn't
    actually say that specific thing), and a fabricated document_id (empty evidence
    text, always unsupported). See DECISIONS.md for why NLI over a second LLM call.
    """

    def __init__(self, model_name=MODEL_NAME, docs_path=DOCS_PATH):
        self.model = CrossEncoder(model_name)
        self.content_by_id = load_content_by_id(docs_path)

    def _entailment_prob(self, premise, hypothesis):
        logits = self.model.predict([(premise, hypothesis)])[0]
        return float(_softmax(logits)[ENTAILMENT_INDEX])

    def verify_claim(self, claim):
        evidence_text = " ".join(
            self.content_by_id.get(doc_id, "") for doc_id in claim.cited_document_ids
        ).strip()
        if not evidence_text:
            return {"claim": claim, "supported": False, "entailment_prob": 0.0, "reason": "cited document not found"}
        prob = self._entailment_prob(evidence_text, claim.text)
        return {"claim": claim, "supported": prob >= ENTAILMENT_THRESHOLD, "entailment_prob": prob}

    def verify(self, answer):
        """Returns {"grounded": bool, "claim_results": [...]}. An answer with zero
        claims is not grounded -- there's nothing to have verified.
        """
        claim_results = [self.verify_claim(c) for c in answer.claims]
        grounded = bool(claim_results) and all(r["supported"] for r in claim_results)
        return {"grounded": grounded, "claim_results": claim_results}


def main():
    judge = GroundednessJudge()

    class _Claim:
        def __init__(self, text, cited_document_ids):
            self.text = text
            self.cited_document_ids = cited_document_ids

    class _Answer:
        def __init__(self, claims):
            self.claims = claims

    cases = [
        # supported: T1059's real content covers this
        _Claim("T1059 covers abuse of command and scripting interpreters to execute commands or scripts.", ["mitre_attack:T1059"]),
        # misattribution: true statement, wrong citation (PowerShell is T1059.001, not T1059 itself)
        _Claim("T1059 specifically refers to the use of PowerShell for credential dumping.", ["mitre_attack:T1059"]),
        # fabricated citation
        _Claim("T1059 was first documented in 1998.", ["mitre_attack:T9999-does-not-exist"]),
    ]
    result = judge.verify(_Answer(cases))
    print(f"grounded={result['grounded']}\n")
    for r in result["claim_results"]:
        print(f"  supported={r['supported']}  p={r['entailment_prob']:.3f}  {r['claim'].text}")


if __name__ == "__main__":
    main()
