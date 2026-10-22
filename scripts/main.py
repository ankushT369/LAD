import os
import glob
import json
import time
from client import qdrant_client, create_collection
from vectorstore import get_vectorstore
from text_utils import build_context
from rag_chain import get_rag_chain


if __name__ == "__main__":

    # Connect to Qdrant
    client = qdrant_client()

    # Create collection if not exists
    collection_name = create_collection(client)
    print(f"Collection created: {collection_name}")

    # Load vector store
    vector_store = get_vectorstore(client, collection_name)

    # Load retrieval-augmented chain
    chain = get_rag_chain()

    # Follow the dated files written by the Fluentd file output plugin.
    log_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "daemon", "logs"))
    log_handles = {}
    waiting_notice_shown = False
    try:
        while True:
            log_files = glob.glob(os.path.join(log_dir, "data.log.*.log"))
            for log_file in log_files:
                if log_file not in log_handles:
                    handle = open(log_file, "r", encoding="utf-8")
                    handle.seek(0, os.SEEK_END)
                    log_handles[log_file] = handle
                    print(f"Following Fluentd output: {log_file}")

            if not log_handles and not waiting_notice_shown:
                print("Waiting for Fluentd to write its first log record...")
                waiting_notice_shown = True

            for handle in log_handles.values():
                line = handle.readline()
                while line:
                    line = line.strip()
                    if line:
                        record = {}
                        try:
                            record = json.loads(line)
                            query = record.get("message", line) if isinstance(record, dict) else line
                        except json.JSONDecodeError:
                            query = line

                        metadata = {
                            "file": record.get("file", "unknown")
                            if isinstance(record, dict)
                            else "unknown",
                            "source": "live_log",
                        }
                        print("New Fluentd record received; storing it in Qdrant...", flush=True)
                        vector_store.add_texts([query], metadatas=[metadata])
                        print("Log stored; searching Qdrant...", flush=True)
                        results = vector_store.similarity_search_with_score(query, k=3)
                        context = build_context(results)
                        print("Qdrant search complete; asking Gemini for classification...", flush=True)
                        try:
                            response = chain({"query": query, "context": context})
                        except Exception as exc:
                            print(f"Gemini classification failed: {exc}", flush=True)
                            line = handle.readline()
                            continue
                        print("\n=== Response ===")
                        print(response, flush=True)
                    line = handle.readline()
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Exiting.")
    finally:
        for handle in log_handles.values():
            handle.close()
