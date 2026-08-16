from pathlib import Path

from qdrant_client import QdrantClient
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

    def search(self, query, limit=10):
        vector = self.model.encode(query, normalize_embeddings=True)
        hits = self.client.query_points(
            collection_name=self.collection,
            query=vector,
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
