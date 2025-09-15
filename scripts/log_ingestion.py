# ingest_apache.py
import os
from client import qdrant_client, create_collection
from vectorstore import get_vectorstore
from text_utils import chunk_text

def ingest_logs(file_path="Apache_2k.log", collection_name="apache_logs_collection"):
    client = qdrant_client()
    collection_name = create_collection(client, collection_name)
    vector_store = get_vectorstore(client, collection_name)

    with open(file_path, "r", encoding="utf-8") as f:
        raw_logs = f.read()

    chunks = chunk_text(raw_logs, chunk_size=500, overlap=50)

    texts = [chunk.strip() for chunk in chunks if chunk.strip()]
    vector_store.add_texts(texts)
    print(f"Ingested {len(texts)} log chunks into collection '{collection_name}'")

if __name__ == "__main__":
    ingest_logs()
