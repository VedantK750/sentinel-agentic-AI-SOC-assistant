import json
import pickle
import re
from pathlib import Path

from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[1]
DOCS_PATH = ROOT / "data" / "documents.json"
BM25_PATH = ROOT / "data" / "bm25_index.pkl"
META_PATH = ROOT / "data" / "bm25_meta.json"

_TOKEN_RE = re.compile(r"[a-zA-Z0-9]+")


def tokenize(text):
    return _TOKEN_RE.findall(text.lower())


def build_corpus(documents):
    tokenized = []
    for doc in documents:
        doc_id = doc.get("id", "")
        combined = " ".join(
            [
                *([doc_id] * 10),
                doc.get("title", ""),
                doc.get("content", ""),
                doc.get("raw", ""),
            ]
        )
        tokenized.append(tokenize(combined))
    return tokenized


def main():
    with open(DOCS_PATH, "r", encoding="utf-8") as f:
        documents = json.load(f)

    corpus = build_corpus(documents)
    bm25 = BM25Okapi(corpus)

    meta = [
        {"index": i, "id": d["id"], "title": d["title"], "source": d["source"]}
        for i, d in enumerate(documents)
    ]

    with open(BM25_PATH, "wb") as f:
        pickle.dump(bm25, f)
    with open(META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)

    print(f"indexed {len(documents)} docs -> {BM25_PATH} + {META_PATH}")

    for query in ["curl file upload", "dump passwords from memory", "T1059"]:
        scores = bm25.get_scores(tokenize(query))
        ranked = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)[:3]
        print(f"\nquery: {query!r}")
        for i, score in ranked:
            print(f"  {score:.2f}  {meta[i]['id']}  {meta[i]['title']}")


if __name__ == "__main__":
    main()
