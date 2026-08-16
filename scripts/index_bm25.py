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


def native_id(doc):
    """The source-specific identifier (ATT&CK technique ID, Sigma rule ID) --
    what the old flat "id" field used to hold before the document_id schema
    refactor. Repeated in the corpus text below to keep exact-ID lookups
    (e.g. "T1059") weighted the way they were before the refactor.
    """
    metadata = doc.get("metadata", {})
    return metadata.get("technique_id") or metadata.get("rule_id") or doc["document_id"]


def build_corpus(documents):
    tokenized = []
    for doc in documents:
        combined = " ".join(
            [
                *([native_id(doc)] * 10),
                doc.get("title", ""),
                doc.get("content", ""),
                doc.get("metadata", {}).get("raw", ""),
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
        {
            "index": i,
            "document_id": d["document_id"],
            "title": d["title"],
            "doc_type": d["doc_type"],
            "source": d["source"]["name"],
        }
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
            print(f"  {score:.2f}  {meta[i]['document_id']}  {meta[i]['title']}")


if __name__ == "__main__":
    main()
