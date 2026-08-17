import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCS_PATH = ROOT / "data" / "documents.json"


def load_documents(docs_path=DOCS_PATH):
    return json.loads(Path(docs_path).read_text(encoding="utf-8"))


def load_content_by_id(docs_path=DOCS_PATH):
    """{document_id: content} for every document -- the lookup CrossEncoderReranker,
    ExactMatchBooster, and the generation pipeline all need, kept in one place so it
    can't drift the way the BM25 tokenizer once did (see DECISIONS.md).
    """
    return {doc["document_id"]: doc.get("content", "") for doc in load_documents(docs_path)}
