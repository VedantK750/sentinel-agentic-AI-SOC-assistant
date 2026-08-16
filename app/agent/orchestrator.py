from .router import IntentRouter
from .tools import build_default_registry

# Maps a read intent to (tool name, fixed extra kwargs). Intent and tool are
# deliberately not the same thing: multiple intents can call the same tool
# differently -- explain_technique and search_knowledge_base both end up calling
# the search_knowledge_base tool, just with a different doc_type filter.
READ_INTENT_TOOLS = {
    "explain_technique": ("search_knowledge_base", {"doc_type": "attack_technique"}),
    "search_detection_rule": ("search_sigma_rules", {}),
    "search_knowledge_base": ("search_knowledge_base", {}),
}


class Orchestrator:
    """Minimal glue between the intent router and the tool registry -- the "Read
    vs Write" branch in PLAN §3's architecture diagram. Deliberately thin: for
    read intents it just calls the matching tool; for write intents it stops at
    reporting the classification, since the propose-confirm-execute pipeline
    (RBAC, confirmation, idempotency, audit -- PLAN §17-22 / Phase 7) doesn't
    exist yet. Building slot-filling to turn "block that IP" into a validated
    BlockIPInput is also intentionally out of scope here -- that's the Action
    Planner box in PLAN's diagram, which only makes sense to build once there's
    somewhere real for it to hand off to.
    """

    def __init__(self, router=None, registry=None):
        self.router = router or IntentRouter()
        self.registry = registry or build_default_registry()

    def handle(self, query):
        result = self.router.classify(query)

        if result.intent == "clarify":
            return {
                "intent": "clarify",
                "confidence": result.confidence,
                "message": result.message,
            }

        if result.category == "write":
            return {
                "intent": result.intent,
                "category": "write",
                "confidence": result.confidence,
                "status": "not_executed",
                "message": (
                    f"Classified as a write action ({result.intent}) with confidence "
                    f"{result.confidence:.2f}. Routing is correct, but execution requires "
                    "RBAC + confirmation (PLAN §17-19 / Phase 7), which isn't built yet."
                ),
            }

        tool_name, extra_kwargs = READ_INTENT_TOOLS[result.intent]
        tool_result = self.registry.call(tool_name, query=query, **extra_kwargs)
        return {
            "intent": result.intent,
            "category": "read",
            "confidence": result.confidence,
            "tool": tool_name,
            **tool_result,
        }


def main():
    orchestrator = Orchestrator()
    queries = [
        "What is T1059?",
        "How do I detect mimikatz?",
        "Tell me about ransomware",
        "Block 185.220.101.5, it's malicious",
        "Please isolate HOST-042",
        "What's the weather like today",
    ]
    for query in queries:
        result = orchestrator.handle(query)
        print(f"\nquery: {query!r}")
        print(f"  intent={result['intent']}  category={result.get('category')}  confidence={result['confidence']:.2f}")
        if "message" in result:
            print(f"  {result['message']}")
        if "results" in result:
            for r in result["results"][:3]:
                print(f"    {r['document_id']}  {r['title']}")


if __name__ == "__main__":
    main()
