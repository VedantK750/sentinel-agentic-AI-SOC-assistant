"""Stage-by-stage latency probe for the full read-query pipeline (PLAN §3):
model construction, intent routing, retrieval+rerank+boost, and generation
(broken down per individual LLM call and per groundedness-verify pass, since
GenerationPipeline's retry logic can chain multiple of each for one query).

Built to answer a concrete question -- "why does a single query take minutes"
-- with real per-stage numbers instead of guessing which stage dominates.
`generate`/`verify` are wrapped with timers rather than reimplementing the
pipeline here, so this reflects actual retry behavior, not an idealized
single-pass timing.

Run: python -m scripts.measure_latency
"""
import functools
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent.router import IntentRouter  # noqa: E402
from app.agent.tools import build_default_registry  # noqa: E402
from app.generation.generator import Generator  # noqa: E402
from app.generation.groundedness import GroundednessJudge  # noqa: E402
from app.generation.pipeline import GenerationPipeline  # noqa: E402
from app.retrieval.documents import load_content_by_id  # noqa: E402

QUERIES = [
    "What is T1059?",
    "How do I detect mimikatz?",
    "What are some Github hacks?",
    "How to do sudo privilege escalation on Linux?",
    "Tell me about ransomware",
]

READ_INTENT_TOOLS = {
    "explain_technique": ("search_knowledge_base", {"doc_type": "attack_technique"}),
    "search_detection_rule": ("search_sigma_rules", {}),
    "search_knowledge_base": ("search_knowledge_base", {}),
}


def _time_calls(obj, method_name, bucket):
    """Wraps obj.method_name in place so every call's duration is appended to
    `bucket`, without changing what the pipeline actually does or how many
    times it calls it.
    """
    original = getattr(obj, method_name)

    @functools.wraps(original)
    def wrapper(*args, **kwargs):
        t0 = time.perf_counter()
        result = original(*args, **kwargs)
        bucket.append(time.perf_counter() - t0)
        return result

    setattr(obj, method_name, wrapper)


def main():
    print("Constructing models (router, retrieval tools, generator, groundedness judge)...")
    t0 = time.perf_counter()
    router = IntentRouter()
    registry = build_default_registry()
    generator = Generator()
    judge = GroundednessJudge()
    pipeline = GenerationPipeline(generator=generator, judge=judge)
    content_by_id = load_content_by_id()
    construction_time = time.perf_counter() - t0
    print(f"  model construction: {construction_time:.2f}s\n")

    totals = []

    for query in QUERIES:
        print(f"{'=' * 70}\nquery: {query!r}")
        llm_calls, verify_calls = [], []
        _time_calls(generator, "generate", llm_calls)
        _time_calls(judge, "verify", verify_calls)

        t_total = time.perf_counter()

        t = time.perf_counter()
        route_result = router.classify(query)
        route_time = time.perf_counter() - t

        if route_result.intent == "clarify" or route_result.category == "write":
            print(f"  not a read query ({route_result.intent}) -- skipped")
            continue

        tool_name, extra = READ_INTENT_TOOLS[route_result.intent]
        t = time.perf_counter()
        tool_result = registry.call(tool_name, query=query, **extra)
        retrieve_time = time.perf_counter() - t

        evidence = [
            {"document_id": r["document_id"], "title": r["title"], "content": content_by_id.get(r["document_id"], "")}
            for r in tool_result["results"]
        ]

        t = time.perf_counter()
        result = pipeline.answer(query, evidence)
        pipeline_time = time.perf_counter() - t

        total_time = time.perf_counter() - t_total
        totals.append(total_time)

        print(f"  route:               {route_time:6.2f}s")
        print(f"  retrieve+rerank+boost:{retrieve_time:6.2f}s")
        print(f"  generation pipeline: {pipeline_time:6.2f}s  ({len(llm_calls)} LLM call(s), {len(verify_calls)} verify pass(es))")
        for i, s in enumerate(llm_calls, 1):
            print(f"    LLM call {i}:       {s:6.2f}s")
        for i, s in enumerate(verify_calls, 1):
            print(f"    verify pass {i}:    {s:6.2f}s")
        print(f"  TOTAL (excl. model construction): {total_time:6.2f}s")
        print(f"  claims={len(result['claims'])}  grounded={result['grounded']}  attempts={result['attempts']}")
        print()

    if totals:
        print(f"{'=' * 70}\nmean query total: {sum(totals)/len(totals):.2f}s  (model construction, paid once per process, NOT included above)")


if __name__ == "__main__":
    main()
