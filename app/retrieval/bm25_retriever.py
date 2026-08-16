import json
import pickle
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BM25_PATH = ROOT / "data" / "bm25_index.pkl"
META_PATH = ROOT / "data" / "bm25_meta.json"

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text):
    return _TOKEN_RE.findall(text.lower())


class BM25Retriever:
    def __init__(self, bm25_path=BM25_PATH, meta_path=META_PATH):
        with open(bm25_path, "rb") as f:
            self.bm25 = pickle.load(f)
        with open(meta_path, "r", encoding="utf-8") as f:
            self.meta = json.load(f)

    def search(self, query, limit=10):
        scores = self.bm25.get_scores(tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:limit]
        return [
            {
                "id": self.meta[i]["id"],
                "title": self.meta[i]["title"],
                "source": self.meta[i]["source"],
                "score": float(score),
            }
            for i, score in ranked
            if score > 0
        ]
