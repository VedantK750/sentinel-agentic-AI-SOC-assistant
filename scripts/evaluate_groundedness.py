"""Benchmark candidate groundedness-judge (NLI) models against a labeled test set.

For each candidate: auto-detect the entailment label index from the model's own
config (don't hardcode/assume -- different checkpoints use different label orders),
score every case in groundedness_eval_data.py, and report per-category accuracy plus
a phrasing-consistency metric (score spread across independently-worded restatements
of the same true fact). Phrasing consistency directly targets a real production bug:
the same true fact scored 0.851 vs 0.125 entailment depending only on wording
(see DECISIONS.md, "GenerationPipeline was silently discarding already-verified
claims on retry" and the model-swap entry above it).

Run: python -m scripts.evaluate_groundedness
"""
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from sentence_transformers import CrossEncoder

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.retrieval.documents import DOCS_PATH, load_content_by_id  # noqa: E402
from scripts.groundedness_eval_data import CASES, EXPECTED_ENTAILED  # noqa: E402

THRESHOLD = 0.5

CANDIDATES = [
    "MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli",               # original baseline
    "MoritzLaurer/DeBERTa-v3-large-mnli-fever-anli-ling-wanli",    # current production model
    "MoritzLaurer/DeBERTa-v3-base-mnli-fever-docnli-ling-2c",      # DocNLI: long-premise/short-hypothesis, matches our task shape
    "cross-encoder/nli-deberta-v3-large",                          # larger version of the model rejected early on
    "sileod/deberta-v3-base-tasksource-nli",                       # broad multi-task NLI (~600 tasks)
]


def softmax(x):
    e = np.exp(x - np.max(x))
    return e / e.sum()


def find_entailment_index(model):
    id2label = model.config.id2label
    for idx, label in id2label.items():
        if "entail" in label.lower():
            return int(idx)
    raise ValueError(f"couldn't find an 'entailment' label in {id2label}")


def run_candidate(model_name, content_by_id):
    print(f"\n{'=' * 70}\n{model_name}\n{'=' * 70}")
    t0 = time.time()
    model = CrossEncoder(model_name)
    entail_idx = find_entailment_index(model)
    print(f"id2label={model.config.id2label}  -> entailment index={entail_idx}  (load {time.time()-t0:.1f}s)")

    results = []
    for case in CASES:
        premise = content_by_id[case["evidence_doc"]]
        hypothesis = case["claim"]
        logits = model.predict([(premise, hypothesis)])[0]
        p_entail = float(softmax(logits)[entail_idx])
        predicted = p_entail >= THRESHOLD
        expected = EXPECTED_ENTAILED[case["category"]]
        results.append({
            "id": case["id"], "category": case["category"],
            "p_entail": p_entail, "predicted": predicted, "expected": expected,
            "correct": predicted == expected,
        })

    n_correct = sum(r["correct"] for r in results)
    print(f"\nOverall accuracy: {n_correct}/{len(results)} ({n_correct/len(results):.0%})")

    by_cat = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)
    for cat, rs in by_cat.items():
        acc = sum(r["correct"] for r in rs) / len(rs)
        print(f"  {cat:15} {sum(r['correct'] for r in rs)}/{len(rs)} ({acc:.0%})")

    # Phrasing consistency: for "supported" cases, group by evidence doc (3 phrasings
    # each) and measure the spread (max-min) of p_entail within each group. A low
    # spread means the model is judging based on the underlying fact, not the wording.
    supported = [r for r in results if r["category"] == "supported"]
    groups = defaultdict(list)
    for r, case in zip(supported, [c for c in CASES if c["category"] == "supported"]):
        groups[case["evidence_doc"]].append(r["p_entail"])
    spreads = [max(v) - min(v) for v in groups.values()]
    print("\nPhrasing consistency (spread across 3 rewordings of the same fact, lower=better):")
    for doc, vals in groups.items():
        print(f"  {doc:45} scores={[f'{v:.3f}' for v in vals]}  spread={max(vals)-min(vals):.3f}")
    print(f"  mean spread: {np.mean(spreads):.3f}")

    wrong = [r for r in results if not r["correct"]]
    if wrong:
        print(f"\n{len(wrong)} misclassification(s):")
        for r in wrong:
            print(f"  [{r['category']}] p={r['p_entail']:.3f} predicted_entailed={r['predicted']} expected={r['expected']}  ({r['id']})")

    return {
        "model": model_name,
        "accuracy": n_correct / len(results),
        "mean_phrasing_spread": float(np.mean(spreads)),
        "n_wrong": len(wrong),
    }


def main():
    content_by_id = load_content_by_id(DOCS_PATH)
    summary = []
    for name in CANDIDATES:
        try:
            summary.append(run_candidate(name, content_by_id))
        except Exception as e:
            print(f"\n!!! {name} FAILED: {e!r}")
            summary.append({"model": name, "accuracy": None, "mean_phrasing_spread": None, "n_wrong": None, "error": repr(e)})

    print(f"\n\n{'=' * 70}\nSUMMARY\n{'=' * 70}")
    print(f"{'model':<55}{'accuracy':<12}{'mean_spread':<14}{'n_wrong'}")
    for s in summary:
        if s.get("error"):
            print(f"{s['model']:<55}FAILED: {s['error']}")
        else:
            print(f"{s['model']:<55}{s['accuracy']:<12.0%}{s['mean_phrasing_spread']:<14.3f}{s['n_wrong']}")


if __name__ == "__main__":
    main()
