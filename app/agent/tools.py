from dataclasses import dataclass
from typing import Callable, Optional, Type

from pydantic import BaseModel

from app.retrieval.exact_match import ExactMatchBooster
from app.retrieval.hybrid import HybridSearcher
from app.retrieval.reranker import CrossEncoderReranker

RERANK_CANDIDATE_LIMIT = 20


# --- typed tool inputs (PLAN §13: "typed input") ---------------------------


class SearchKnowledgeBaseInput(BaseModel):
    query: str
    limit: int = 5
    doc_type: Optional[str] = None


class SearchSigmaRulesInput(BaseModel):
    query: str
    limit: int = 5


class LookupIOCInput(BaseModel):
    ioc: str


class GetAlertInput(BaseModel):
    alert_id: str


class GetIncidentInput(BaseModel):
    incident_id: str


class CreateIncidentInput(BaseModel):
    title: str
    description: str
    related_technique_ids: list = []


class BlockIPInput(BaseModel):
    ip_address: str
    reason: str


class IsolateEndpointInput(BaseModel):
    hostname: str
    reason: str


@dataclass
class Tool:
    """A tool's full declared contract per PLAN §13. RBAC/idempotency-store/audit-log
    don't exist yet (Phases 7-8), so `required_permission`/`idempotent`/`audit_event`
    are declarative only right now -- nothing enforces them. They exist so that when
    Phase 7 builds the enforcement layer, it has a contract to read from instead of
    hardcoding tool-specific logic.
    """

    name: str
    description: str
    category: str  # "read" | "write"
    side_effecting: bool
    idempotent: bool
    required_permission: Optional[str]
    audit_event: bool
    input_model: Type[BaseModel]
    handler: Callable


class ToolRegistry:
    def __init__(self):
        self._tools = {}

    def register(self, tool):
        self._tools[tool.name] = tool
        return tool

    def get(self, name):
        return self._tools.get(name)

    def call(self, name, **kwargs):
        tool = self.get(name)
        if tool is None:
            raise KeyError(f"unknown tool: {name!r}")
        validated = tool.input_model(**kwargs)
        return tool.handler(validated)


# --- lazily-constructed shared retrieval components -------------------------
# One HybridSearcher/CrossEncoderReranker per process, not per call, for the same
# reason app/retrieval components are designed to be long-lived (see ARCHITECTURE.md).

_searcher = None
_reranker = None
_booster = None


def _get_searcher():
    global _searcher
    if _searcher is None:
        _searcher = HybridSearcher()
    return _searcher


def _get_reranker():
    global _reranker
    if _reranker is None:
        _reranker = CrossEncoderReranker()
    return _reranker


def _get_booster():
    global _booster
    if _booster is None:
        _booster = ExactMatchBooster()
    return _booster


def _search(query, limit, doc_type=None):
    """RRF hybrid search, then cross-encoder rerank, then exact-match boosting --
    the full pipeline. RRF+rerank was the best-measured combination in Phase 4;
    boosting on top handles known-item queries (exact technique/rule IDs) that
    rank-based fusion can under-rank even when one retriever found them at #1 --
    see DECISIONS.md.
    """
    searcher = _get_searcher()
    reranker = _get_reranker()
    booster = _get_booster()
    candidates = searcher.search(query, limit=RERANK_CANDIDATE_LIMIT, doc_type=doc_type)
    reranked = reranker.rerank(query, candidates, limit=RERANK_CANDIDATE_LIMIT)
    return booster.boost(query, reranked, limit=limit)


# --- read tool handlers (real, backed by retrieval) --------------------------


def _handle_search_knowledge_base(input: SearchKnowledgeBaseInput):
    results = _search(input.query, limit=input.limit, doc_type=input.doc_type)
    return {"results": results}


def _handle_search_sigma_rules(input: SearchSigmaRulesInput):
    results = _search(input.query, limit=input.limit, doc_type="detection_rule")
    return {"results": results}


# --- read tool handlers (stubs -- no data source built yet) ------------------


def _handle_lookup_ioc(input: LookupIOCInput):
    return {"error": "no IOC data source configured yet (PLAN §4.4 / Phase 1 not built)"}


def _handle_get_alert(input: GetAlertInput):
    return {"error": "no alert data source yet (PLAN §4.4 / Phase 1 not built)"}


def _handle_get_incident(input: GetIncidentInput):
    return {"error": "no incident store yet (PLAN §23 PostgreSQL / Phase 8 not built)"}


# --- write tool handlers (stubs -- no RBAC/confirm/execute pipeline yet) -----


def _handle_create_incident(input: CreateIncidentInput):
    return {
        "status": "not_executed",
        "reason": "write actions require RBAC + confirmation (PLAN §17-19 / Phase 7), not yet implemented",
        "proposed_action": {"tool": "create_incident", **input.model_dump()},
    }


def _handle_block_ip(input: BlockIPInput):
    return {
        "status": "not_executed",
        "reason": "write actions require RBAC + confirmation (PLAN §17-19 / Phase 7), not yet implemented",
        "proposed_action": {"tool": "block_ip", **input.model_dump()},
    }


def _handle_isolate_endpoint(input: IsolateEndpointInput):
    return {
        "status": "not_executed",
        "reason": "write actions require RBAC + confirmation (PLAN §17-19 / Phase 7), not yet implemented",
        "proposed_action": {"tool": "isolate_endpoint", **input.model_dump()},
    }


def build_default_registry():
    registry = ToolRegistry()

    registry.register(
        Tool(
            name="search_knowledge_base",
            description="Hybrid (BM25 + vector, RRF-fused, reranked) search over the full knowledge base, optionally filtered by doc_type.",
            category="read",
            side_effecting=False,
            idempotent=True,
            required_permission="knowledge.read",
            audit_event=False,
            input_model=SearchKnowledgeBaseInput,
            handler=_handle_search_knowledge_base,
        )
    )
    registry.register(
        Tool(
            name="search_sigma_rules",
            description="Hybrid search restricted to Sigma detection rules (doc_type=detection_rule).",
            category="read",
            side_effecting=False,
            idempotent=True,
            required_permission="knowledge.read",
            audit_event=False,
            input_model=SearchSigmaRulesInput,
            handler=_handle_search_sigma_rules,
        )
    )
    registry.register(
        Tool(
            name="lookup_ioc",
            description="Look up a known indicator of compromise (IP, hash, domain).",
            category="read",
            side_effecting=False,
            idempotent=True,
            required_permission="knowledge.read",
            audit_event=False,
            input_model=LookupIOCInput,
            handler=_handle_lookup_ioc,
        )
    )
    registry.register(
        Tool(
            name="get_alert",
            description="Fetch a security alert by ID.",
            category="read",
            side_effecting=False,
            idempotent=True,
            required_permission="alerts.read",
            audit_event=False,
            input_model=GetAlertInput,
            handler=_handle_get_alert,
        )
    )
    registry.register(
        Tool(
            name="get_incident",
            description="Fetch an incident record by ID.",
            category="read",
            side_effecting=False,
            idempotent=True,
            required_permission="incidents.read",
            audit_event=False,
            input_model=GetIncidentInput,
            handler=_handle_get_incident,
        )
    )
    registry.register(
        Tool(
            name="create_incident",
            description="Create a new incident record.",
            category="write",
            side_effecting=True,
            idempotent=False,
            required_permission="incidents.create",
            audit_event=True,
            input_model=CreateIncidentInput,
            handler=_handle_create_incident,
        )
    )
    registry.register(
        Tool(
            name="block_ip",
            description="Block an IP address on the corporate firewall.",
            category="write",
            side_effecting=True,
            idempotent=True,  # blocking an already-blocked IP is a safe no-op, not a compounding action
            required_permission="network.block_ip",
            audit_event=True,
            input_model=BlockIPInput,
            handler=_handle_block_ip,
        )
    )
    registry.register(
        Tool(
            name="isolate_endpoint",
            description="Isolate an endpoint from the network via EDR.",
            category="write",
            side_effecting=True,
            idempotent=True,  # isolating an already-isolated host is a safe no-op
            required_permission="endpoint.isolate",
            audit_event=True,
            input_model=IsolateEndpointInput,
            handler=_handle_isolate_endpoint,
        )
    )
    return registry


def main():
    registry = build_default_registry()
    print("registered tools:")
    for name, tool in registry._tools.items():
        print(
            f"  {name:22} category={tool.category:6} side_effecting={tool.side_effecting!s:5} "
            f"idempotent={tool.idempotent!s:5} permission={tool.required_permission}"
        )

    print("\nsearch_knowledge_base('T1059'):")
    for r in registry.call("search_knowledge_base", query="T1059", limit=3)["results"]:
        print(f"  {r['document_id']}  {r['title']}")

    print("\nsearch_sigma_rules('credential dumping'):")
    for r in registry.call("search_sigma_rules", query="credential dumping", limit=3)["results"]:
        print(f"  {r['document_id']}  {r['title']}")

    print("\nblock_ip(ip_address='185.220.101.5', reason='malicious IOC'):")
    print(" ", registry.call("block_ip", ip_address="185.220.101.5", reason="malicious IOC"))


if __name__ == "__main__":
    main()
