"""
Simple fuzzy keyword search over the notes/remarks free-text column.
This is a deliberate scope cut for the time budget: a full embeddings-based
RAG pipeline (chromadb + sentence-transformers) is the natural upgrade and is
documented as such in the Decision Log, but keyword/fuzzy search already
covers "which deals mentioned X" style questions without an extra dependency
or API cost.
"""
from rapidfuzz import fuzz


def search_notes(df, keyword: str, top_k: int = 5):
    if df is None or df.empty or "notes" not in df.columns or not keyword:
        return []
    results = []
    for _, row in df.iterrows():
        note = row.get("notes")
        if not note:
            continue
        score = fuzz.partial_ratio(keyword.lower(), str(note).lower())
        if score >= 55:
            results.append({
                "id": row.get("id"),
                "name": row.get("name"),
                "client": row.get("client"),
                "note": note,
                "score": round(score, 1),
            })
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_k]
