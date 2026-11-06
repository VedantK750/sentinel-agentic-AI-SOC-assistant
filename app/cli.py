"""Manual testing entry point: run any query through the full system end to end
(intent router -> tool -> retrieval+rerank+boost -> generation -> groundedness
judge) and see every stage's output. Not the API layer -- app/main.py (Phase 8)
will be the FastAPI entrypoint, built around this same Orchestrator.

Usage:
    python -m app.cli "What is T1059?"
"""
import sys
import textwrap

from app.agent.orchestrator import Orchestrator
from app.generation.render import render_answer


def main():
    if len(sys.argv) < 2:
        print('usage: python -m app.cli "your query here"')
        sys.exit(1)
    query = " ".join(sys.argv[1:])

    print("(loading models -- first run downloads a few, takes a bit)")
    orchestrator = Orchestrator()

    result = orchestrator.handle(query)

    print(f"\nquery: {query!r}")
    print(f"intent: {result['intent']}   category: {result.get('category')}   confidence: {result['confidence']:.2f}")

    if result["intent"] == "clarify":
        print(f"\n{result['message']}")
        return

    if result.get("category") == "write":
        print(f"\n{result['message']}")
        return

    print(f"tool: {result['tool']}")

    print("\nretrieved evidence:")
    for r in result.get("retrieved", []):
        tag = " [EXACT MATCH]" if r.get("exact_match") else ""
        print(f"  {r['document_id']:45}  {r['title']}{tag}")

    print(f"\ngrounded: {result['grounded']}   insufficient_evidence: {result['insufficient_evidence']}   attempts: {result['attempts']}")
    if result.get("message"):
        print(f"  note: {result['message']}")

    print("\nanswer:")
    if not result["claims"]:
        print("  (no claims -- insufficient evidence to answer)")
    else:
        rendered = render_answer(result["claims"], result.get("retrieved", []))
        print(textwrap.fill(rendered["text"], width=100, initial_indent="  ", subsequent_indent="  "))

        print("\nsources:")
        for ref in rendered["references"]:
            url_part = f" -- {ref['url']}" if ref["url"] else ""
            print(f"  [{ref['marker']}] {ref['title']} ({ref['source']}){url_part}")


if __name__ == "__main__":
    main()
