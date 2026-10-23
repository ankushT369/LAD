import os
import glob
import json
import time
import signal
from datetime import datetime, timezone
from client import qdrant_client, create_collection
from vectorstore import get_vectorstore
from text_utils import build_context
from rag_chain import get_rag_chain


def parse_classification(response):
    """Decode the classifier JSON, including JSON wrapped in Markdown fences."""
    text = str(response).strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()

    classification = json.loads(text)
    if not isinstance(classification, dict):
        raise ValueError("Classifier response must be a JSON object")
    return classification


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
    dashboard_path = os.path.join(log_dir, "dashboard_events.jsonl")
    waiting_notice_shown = False
    stopping = False

    def request_stop(_signum, _frame):
        global stopping
        stopping = True

    signal.signal(signal.SIGTERM, request_stop)

    def interrupt_now(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGINT, interrupt_now)

    # Files that existed before this worker started may contain old output. Start
    # those at EOF, but read newly created Fluentd output files from byte zero:
    # Fluentd can flush the first records before the next glob discovers a file.
    known_files = set(glob.glob(os.path.join(log_dir, "data.log.*.log")))
    active_event = None
    try:
        while True:
            log_files = glob.glob(os.path.join(log_dir, "data.log.*.log"))
            for log_file in log_files:
                if log_file not in log_handles:
                    handle = open(log_file, "r", encoding="utf-8")
                    if log_file in known_files:
                        handle.seek(0, os.SEEK_END)
                    known_files.add(log_file)
                    log_handles[log_file] = handle
                    print(f"Following Fluentd output: {log_file}")

            if not log_handles and not waiting_notice_shown:
                print("Waiting for Fluentd to write its first log record...")
                waiting_notice_shown = True

            for handle in list(log_handles.values()):
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
                        event = {
                            "id": f"{os.path.basename(handle.name)}:{handle.tell()}",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "message": query,
                            "file": metadata["file"],
                            "status": "processing",
                        }
                        active_event = event
                        def save_event(update):
                            event.update(update)
                            with open(dashboard_path, "a", encoding="utf-8") as output:
                                output.write(json.dumps(event, ensure_ascii=False) + "\n")

                        save_event({})
                        print("New Fluentd record received; storing it in Qdrant...", flush=True)
                        try:
                            vector_store.add_texts([query], metadatas=[metadata])
                            print("Log stored; searching Qdrant...", flush=True)
                            results = vector_store.similarity_search_with_score(query, k=3)
                            context = build_context(results)
                            print("Qdrant search complete; asking Gemini for classification...", flush=True)
                            response = chain({"query": query, "context": context})
                        except Exception as exc:
                            print(f"Log analysis failed: {exc}", flush=True)
                            save_event({"status": "failed", "error": str(exc)})
                            active_event = None
                            line = handle.readline()
                            continue
                        try:
                            classification = parse_classification(response)
                        except (TypeError, ValueError, json.JSONDecodeError):
                            classification = {"explanation": str(response)}
                        save_event({
                            "status": "analyzed",
                            "anomaly_detected": bool(classification.get("anomaly_detected", False)),
                            "error_type": classification.get("error_type", "none"),
                            "suggested_fix": classification.get("suggested_fix", "none"),
                            "commands": classification.get("commands", []),
                            "explanation": classification.get("explanation", ""),
                            "confidence": classification.get("confidence", "unknown"),
                        })
                        active_event = None
                        print("\n=== Response ===")
                        print(response, flush=True)
                    line = handle.readline()
            if stopping and all(
                os.fstat(handle.fileno()).st_size <= handle.tell()
                for handle in log_handles.values()
            ):
                print("Stop requested; all flushed Fluentd records are processed.", flush=True)
                break
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nKeyboardInterrupt detected. Stopping without draining queued logs.", flush=True)
        if active_event is not None:
            active_event.update({
                "status": "failed",
                "error": "Analysis interrupted by Ctrl+C.",
            })
            with open(dashboard_path, "a", encoding="utf-8") as output:
                output.write(json.dumps(active_event, ensure_ascii=False) + "\n")
    finally:
        for handle in log_handles.values():
            handle.close()
