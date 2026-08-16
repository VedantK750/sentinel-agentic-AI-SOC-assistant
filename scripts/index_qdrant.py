import json
from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[1]
DOCS_PATH = ROOT / "data" / "documents.json"
QDRANT_DIR = ROOT / "data" / "qdrant_db"
COLLECTION = "sentinel_documents"
MODEL_NAME = "all-MiniLM-L6-v2"
BATCH_SIZE = 100
VECTOR_SIZE = 384


def native_id(doc):
    """See scripts/index_bm25.py:native_id -- same rationale, kept consistent
    so BM25 and vector indexing embed/weight the same identifier text.
    """
    metadata = doc.get("metadata", {})
    return metadata.get("technique_id") or metadata.get("rule_id") or doc["document_id"]


def build_texts(documents):
    texts = []
    for doc in documents:
        title = doc.get("title", "")
        content = doc.get("content", "")
        texts.append(f"{native_id(doc)}. {title}. {content}".strip())
    return texts


def main():
    with open(DOCS_PATH, "r", encoding="utf-8") as f:
        documents = json.load(f)

    client = QdrantClient(path=str(QDRANT_DIR))
    if client.collection_exists(COLLECTION):
        client.delete_collection(COLLECTION)
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(
            size=VECTOR_SIZE, distance=models.Distance.COSINE
        ),
    )

    model = SentenceTransformer(MODEL_NAME)
    texts = build_texts(documents)

    for start in range(0, len(texts), BATCH_SIZE):
        batch_texts = texts[start : start + BATCH_SIZE]
        batch_docs = documents[start : start + BATCH_SIZE]
        vectors = model.encode(batch_texts, normalize_embeddings=True)
        points = [
            models.PointStruct(
                id=start + i,
                vector=vectors[i].tolist(),
                payload={
                    "document_id": batch_docs[i]["document_id"],
                    "title": batch_docs[i]["title"],
                    "doc_type": batch_docs[i]["doc_type"],
                    "source": batch_docs[i]["source"]["name"],
                },
            )
            for i in range(len(batch_texts))
        ]
        client.upsert(collection_name=COLLECTION, points=points)
        print(f"  upserted {start + len(points)}/{len(documents)}")

    print(f"indexed {len(documents)} docs -> {QDRANT_DIR} (model={MODEL_NAME})")

    for query in ["dump passwords from memory", "curl file upload", "T1059"]:
        vector = model.encode(query, normalize_embeddings=True)
        hits = client.query_points(
            collection_name=COLLECTION,
            query=vector,
            limit=3,
        ).points
        print(f"\nquery: {query!r}")
        for hit in hits:
            print(
                f"  {hit.score:.4f}  {hit.payload['document_id']}  {hit.payload['title']}"
            )


if __name__ == "__main__":
    main()
