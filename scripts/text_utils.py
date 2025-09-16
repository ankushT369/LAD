import textwrap

def chunk_text(text, chunk_size=500, overlap=50):
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks

def build_context(results, k=3):
    ctx_parts = []
    for i, (doc, score) in enumerate(results, start=1):
        snippet = doc.page_content.strip().replace("\n", " ")
        ctx_parts.append(f"[{i}] (score {score:.4f}) {snippet[:500]}")
    return "\n".join(ctx_parts)
