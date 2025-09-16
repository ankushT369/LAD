from client import qdrant_client, create_collection
from vectorstore import get_vectorstore
from text_utils import build_context
from rag_chain import get_rag_chain


if __name__ == "__main__":
    client = qdrant_client()
    collection_name = create_collection(client)
    print(f"Collection created: {collection_name}")
    vector_store = get_vectorstore(client, collection_name)
    chain = get_rag_chain()

    #print("\nEnter your search query (or 'exit' to quit):")

    while True:
        # trail logs from /logs/data.logs/buffer.b63ee8992fa810b15153db132100359bf.log
        fobj = open("../daemon/logs/data.log/buffer.b63ee8992fa810b15153db132100359bf.log", "r")
        query = fobj.readline()

        # later
        if query.lower() in {"exit", "quit"}:
            break
        if not query:
            continue

        """
        query = input("\nQuery: ").strip()
        if query.lower() in {"exit", "quit"}:
            break
        if not query:
            continue
        """

        # retrieve
        results = vector_store.similarity_search_with_score(query, k=3)
        context = build_context(results)

        response = chain.invoke({"query": query, "context": context})
        print("\n=== Response ===")
        print(response.content)
