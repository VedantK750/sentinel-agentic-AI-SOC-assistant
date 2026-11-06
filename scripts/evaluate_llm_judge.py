"""Compares LLMGroundednessJudge (mistralai/mistral-small-24b-instruct-2501, one
batched call for all claims) against the local NLI judge (groundedness.py) on the
same labeled 18-case set (groundedness_eval_data.py) used to pick the NLI model --
same test set, so accuracy numbers are directly comparable, plus a wall-clock
timing comparison run under the same conditions.

Run: python -m scripts.evaluate_llm_judge
"""
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.generation.groundedness import MODEL_NAME as NLI_MODEL_NAME  # noqa: E402
from app.generation.groundedness import GroundednessJudge  # noqa: E402
from app.generation.llm_judge import LLMGroundednessJudge  # noqa: E402
from scripts.groundedness_eval_data import CASES, EXPECTED_ENTAILED  # noqa: E402


class _Claim:
    def __init__(self, text, cited_document_ids):
        self.text = text
        self.cited_document_ids = cited_document_ids


class _Answer:
    def __init__(self, claims):
        self.claims = claims


def _build_answer():
    return _Answer([_Claim(c["claim"], [c["evidence_doc"]]) for c in CASES])


def _score(claim_results, label):
    n_correct = 0
    by_cat = defaultdict(list)
    wrong = []
    for case, r in zip(CASES, claim_results):
        expected = EXPECTED_ENTAILED[case["category"]]
        correct = r["supported"] == expected
        n_correct += correct
        by_cat[case["category"]].append(correct)
        if not correct:
            wrong.append((case, r))

    print(f"\n--- {label} ---")
    print(f"Overall accuracy: {n_correct}/{len(CASES)} ({n_correct/len(CASES):.0%})")
    for cat, results in by_cat.items():
        acc = sum(results) / len(results)
        print(f"  {cat:15} {sum(results)}/{len(results)} ({acc:.0%})")

    # Phrasing consistency, categorical version: for each of the 3 "supported" fact
    # groups (3 rewordings each), are all 3 phrasings judged the same way? No
    # continuous probability exists for an LLM verdict, so this checks all-or-nothing
    # agreement within a group instead of a numeric spread.
    supported_cases = [c for c in CASES if c["category"] == "supported"]
    supported_results = [r for c, r in zip(CASES, claim_results) if c["category"] == "supported"]
    groups = defaultdict(list)
    for case, r in zip(supported_cases, supported_results):
        groups[case["evidence_doc"]].append(r["supported"])
    consistent_groups = sum(1 for v in groups.values() if len(set(v)) == 1)
    print(f"Phrasing consistency: {consistent_groups}/{len(groups)} fact-groups judged the same across all 3 rewordings")

    if wrong:
        print(f"{len(wrong)} misclassification(s):")
        for case, r in wrong:
            print(f"  [{case['category']}] supported={r['supported']} expected={EXPECTED_ENTAILED[case['category']]}  ({case['id']})  reason={r.get('reason', r.get('entailment_prob'))!r}")

    return n_correct / len(CASES)


def main():
    print("Constructing judges...")

    print("\nRunning LLM judge (single batched call, all 18 claims)...")
    llm_judge = LLMGroundednessJudge()
    t0 = time.perf_counter()
    llm_result = llm_judge.verify(_build_answer())
    llm_time = time.perf_counter() - t0
    _score(llm_result["claim_results"], f"LLM judge ({llm_judge.model}) -- {llm_time:.2f}s total, {llm_time/len(CASES):.2f}s/claim")

    print("\nRunning local NLI judge (for a same-conditions timing baseline)...")
    nli_judge = GroundednessJudge()
    t0 = time.perf_counter()
    nli_result = nli_judge.verify(_build_answer())
    nli_time = time.perf_counter() - t0
    _score(nli_result["claim_results"], f"NLI judge ({NLI_MODEL_NAME}) -- {nli_time:.2f}s total, {nli_time/len(CASES):.2f}s/claim")

    print(f"\n{'=' * 70}\nSUMMARY")
    print(f"LLM judge:  {llm_time:6.2f}s total ({llm_time/len(CASES):.2f}s/claim, 1 API call for all {len(CASES)} claims)")
    print(f"NLI judge:  {nli_time:6.2f}s total ({nli_time/len(CASES):.2f}s/claim, local, no network)")


if __name__ == "__main__":
    main()
