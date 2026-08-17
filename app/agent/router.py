import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

MODEL_NAME = "all-MiniLM-L6-v2"

READ = "read"
WRITE = "write"

# Confidence thresholds the top-scoring intent must clear before the router commits
# to it. Write intents get a stricter bar than read intents: per PLAN §18's
# fail-closed principle, misrouting a query into a read search wastes a query,
# but misrouting into a write action is a worse failure mode -- the router should
# be more willing to say "clarify" than to guess its way into a write intent.
READ_CONFIDENCE_THRESHOLD = 0.35
WRITE_CONFIDENCE_THRESHOLD = 0.55

# The top intent must also beat the runner-up by at least this much. A high top
# score with a near-tied runner-up still means "not sure which one" -- e.g.
# "search_detection_rule" vs "search_knowledge_base" can legitimately both score
# well on a borderline query.
MARGIN_THRESHOLD = 0.05

# search_knowledge_base is the deliberate broad catch-all -- PLAN §12's cascade ends
# in "escalate/clarify when uncertain", but a fallback that's held to the same bar as
# the narrow, specific intents can never actually play that role: it's matching
# against open-ended topic space (any of ~4,000 documents) with only a handful of
# examples, so even a genuine true positive scores lower than a specific intent's true
# positive would. Verified empirically before picking this number, not guessed: on a
# spread of clearly off-topic queries ("hey", weather, pizza, bare "search"), its own
# score topped out at 0.184; on legitimate security questions using vocabulary none of
# its examples cover ("sudo privilege escalation", "DLL sideloading"), it started at
# 0.204. See DECISIONS.md for the full readout and why "block" specifically (0.184,
# right at that boundary) needed the second guard below, not just this number.
FALLBACK_INTENT = "search_knowledge_base"
FALLBACK_CONFIDENCE_THRESHOLD = 0.20

# Additive nudge applied when a lexical/keyword signal fires for an intent, on
# top of its semantic similarity score. Mirrors why retrieval combines BM25 with
# vector search: a generic sentence embedding can blur "block that IP" and
# "isolate that host" together, but an explicit keyword match disambiguates
# instantly the way exact-token matching does for document retrieval.
LEXICAL_BOOST = 0.25

_TECHNIQUE_ID_RE = re.compile(r"\bT\d{4}(?:\.\d{3})?\b", re.IGNORECASE)


@dataclass
class Intent:
    name: str
    category: str  # "read" | "write"
    examples: list
    keywords: list = field(default_factory=list)
    match_technique_id: bool = False


INTENTS = [
    Intent(
        name="explain_technique",
        category=READ,
        examples=[
            "What is T1059?",
            "Explain technique T1003",
            "Tell me about the credential dumping technique",
            "What does the LSASS memory technique do",
            "Describe the command and scripting interpreter technique",
            "What is technique T1566",
        ],
        match_technique_id=True,
    ),
    Intent(
        name="search_detection_rule",
        category=READ,
        examples=[
            "How can I detect suspicious PowerShell?",
            "Show me Sigma rules for credential dumping",
            "What detection rules exist for mimikatz",
            "Find rules that detect lateral movement",
            "Are there any detections for curl file upload",
            "What Sigma rules cover ransomware",
        ],
        keywords=["detect", "detection", "sigma rule", "sigma rules", "rule for", "rules for"],
    ),
    Intent(
        name="search_knowledge_base",
        category=READ,
        examples=[
            "Tell me about ransomware",
            "What is phishing",
            "How does lateral movement work",
            "Explain reverse shells",
            "What is a supply chain attack",
            "How do attackers hack into wifi networks",
            "How is Windows hacked",
            "How do hackers break into a system",
        ],
    ),
    Intent(
        name="block_ip",
        category=WRITE,
        examples=[
            "Block this IP address",
            "Block 185.220.101.5 on the firewall",
            "I want to block that malicious IP",
            "Please block the source IP for this alert",
        ],
        keywords=["block ip", "block the ip", "block that ip", "block this ip"],
    ),
    Intent(
        name="isolate_endpoint",
        category=WRITE,
        examples=[
            "Isolate this endpoint",
            "Isolate host HOST-042 from the network",
            "Quarantine that machine",
            "Disconnect this host from the network",
        ],
        keywords=["isolate", "quarantine"],
    ),
]


@dataclass
class IntentResult:
    intent: str
    category: Optional[str]
    confidence: float
    message: Optional[str] = None


class IntentRouter:
    """Classifies a query into one of INTENTS using the same lexical+semantic
    combination retrieval already uses -- a keyword/pattern signal to catch exact
    phrasing, a sentence-embedding similarity signal to catch paraphrases -- then
    gates the decision on confidence and margin-over-runner-up so an unsure query
    escalates to "clarify" instead of being force-classified. See PLAN §12/§18.
    """

    def __init__(self, intents=None, model_name=MODEL_NAME):
        self.intents = intents if intents is not None else INTENTS
        self.model = SentenceTransformer(model_name)
        self._example_embeddings = {
            intent.name: np.asarray(
                self.model.encode(intent.examples, normalize_embeddings=True)
            )
            for intent in self.intents
        }

    def classify(self, query):
        query_vec = np.asarray(self.model.encode(query, normalize_embeddings=True))

        scored = []
        for intent in self.intents:
            example_matrix = self._example_embeddings[intent.name]
            semantic_score = float(np.max(example_matrix @ query_vec))
            lexical_hit = self._lexical_match(query, intent)
            score = semantic_score + (LEXICAL_BOOST if lexical_hit else 0.0)
            scored.append((intent, score, semantic_score, lexical_hit))

        scored.sort(key=lambda item: item[1], reverse=True)
        top_intent, top_score, top_semantic, top_lexical = scored[0]
        runner_up_score = scored[1][1] if len(scored) > 1 else 0.0
        margin = top_score - runner_up_score

        threshold = WRITE_CONFIDENCE_THRESHOLD if top_intent.category == WRITE else READ_CONFIDENCE_THRESHOLD
        if top_score >= threshold and margin >= MARGIN_THRESHOLD:
            return IntentResult(
                intent=top_intent.name,
                category=top_intent.category,
                confidence=top_score,
            )

        # Nothing cleared its own bar with a clear margin. Before giving up, check
        # whether the broad catch-all applies on its own, lower bar -- but only when
        # the strongest signal was already leaning read. If the strongest (if
        # unconfirmed) signal was a write intent -- e.g. bare "block", which scores
        # 0.54 on block_ip and never even reaches this fallback's own threshold
        # question -- silently reclassifying it as a read search would paper over a
        # write-flavored ambiguity instead of surfacing it. See DECISIONS.md.
        if top_intent.category == READ:
            fallback_score = next(score for intent, score, _, _ in scored if intent.name == FALLBACK_INTENT)
            if fallback_score >= FALLBACK_CONFIDENCE_THRESHOLD:
                return IntentResult(
                    intent=FALLBACK_INTENT,
                    category=READ,
                    confidence=fallback_score,
                )

        return IntentResult(
            intent="clarify",
            category=None,
            confidence=top_score,
            message=(
                f"Not confident enough to route this (best candidate "
                f"'{top_intent.name}' scored {top_score:.2f} vs threshold "
                f"{threshold:.2f}, margin over runner-up {margin:.2f} vs "
                f"required {MARGIN_THRESHOLD:.2f}). Please rephrase or be "
                "more specific."
            ),
        )

    @staticmethod
    def _lexical_match(query, intent):
        if intent.match_technique_id and _TECHNIQUE_ID_RE.search(query):
            return True
        q = query.lower()
        return any(kw in q for kw in intent.keywords)


def main():
    router = IntentRouter()
    queries = [
        "What is T1059?",
        "Explain T1003.001",
        "How do I detect mimikatz?",
        "Show me Sigma rules for lateral movement",
        "Tell me about ransomware",
        "What is a reverse shell",
        "Block 185.220.101.5, it's malicious",
        "Please isolate HOST-042 right now",
        "What's the weather like today",
        "hey",
    ]
    for q in queries:
        result = router.classify(q)
        print(f"{q!r:45} -> intent={result.intent:24} category={str(result.category):6} confidence={result.confidence:.2f}")
        if result.message:
            print(f"    {result.message}")


if __name__ == "__main__":
    main()
