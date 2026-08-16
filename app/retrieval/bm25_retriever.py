import json
import pickle
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BM25_PATH = ROOT / "data" / "bm25_index.pkl"
META_PATH = ROOT / "data" / "bm25_meta.json"

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")

# Classic Okapi BM25's IDF term is log((N - n(t) + 0.5) / (n(t) + 0.5)), which goes
# *negative* once a term appears in more than half the corpus -- so a stopword like
# "is" or "what" doesn't just fail to help, it actively subtracts score from any
# document that happens to contain it often. That's invisible on short keyword
# queries ("T1059", "curl file upload") but breaks natural-language questions
# ("What is T1059?") outright: found empirically when the intent router's
# explain_technique tool returned an unrelated technique for that exact query
# instead of T1059 itself. Filtering stopwords at both index time and query time
# removes the negative-IDF penalty; it must stay identical in both places, which is
# why this is the one place tokenize() is defined -- scripts/index_bm25.py imports
# it rather than keeping its own copy.
STOPWORDS = frozenset(
    """
    a an the is are was were be been being of to in on for and or but if then else
    what which who whom how why when where do does did doing this that these those
    with as at by from it its i you he she we they me him her us them my your his
    their our not no so such than too very can will just about into over again
    further here there all any both each few more most other some only own same
    up down out off also
    """.split()
)


def tokenize(text):
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in STOPWORDS]


class BM25Retriever:
    def __init__(self, bm25_path=BM25_PATH, meta_path=META_PATH):
        with open(bm25_path, "rb") as f:
            self.bm25 = pickle.load(f)
        with open(meta_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)

    def search(self, query, limit=10, doc_type=None):
        scores = self.bm25.get_scores(tokenize(query))
        candidates = enumerate(scores)
        if doc_type is not None:
            allowed = {doc_type} if isinstance(doc_type, str) else set(doc_type)
            candidates = (
                (i, score) for i, score in candidates if self.meta[i]["doc_type"] in allowed
            )
        ranked = sorted(candidates, key=lambda x: x[1], reverse=True)[:limit]
        return [
            {
                "document_id": self.meta[i]["document_id"],
                "title": self.meta[i]["title"],
                "doc_type": self.meta[i]["doc_type"],
                "source": self.meta[i]["source"],
                "score": float(score),
            }
            for i, score in ranked
            if score > 0
        ]
