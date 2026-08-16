from pathlib import Path

from qdrant_client import QdrantClient
from qdrant_client.http import models
from sentence_transformers import SentenceTransformer

ROOT = Path(__file__).resolve().parents[2]
QDRANT_DIR = ROOT / "data" / "qdrant_db"
COLLECTION = "sentinel_documents"
MODEL_NAME = "all-MiniLM-L6-v2"


class VectorRetriever:
    def __init__(self, qdrant_dir=QDRANT_DIR, collection=COLLECTION, model_name=MODEL_NAME):
        self.client = QdrantClient(path=str(qdrant_dir))
        self.collection = collection
        self.model = SentenceTransformer(model_name)

    def search(self, query, limit=10, doc_type=None):
        vector = self.model.encode(query, normalize_embeddings=True)
        query_filter = None
        if doc_type is not None:
            allowed = [doc_type] if isinstance(doc_type, str) else list(doc_type)
            query_filter = models.Filter(
                must=[models.FieldCondition(key="doc_type", match=models.MatchAny(any=allowed))]
            )
        hits = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
        ).points
        return [
            {
                "document_id": hit.payload["document_id"],
                "title": hit.payload["title"],
                "doc_type": hit.payload["doc_type"],
                "source": hit.payload["source"],
                "score": float(hit.score),
            }
            for hit in hits
        ]
