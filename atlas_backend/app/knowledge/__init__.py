"""A knowledge base the crew attaches: procedures, contact sheets, checklists.

Telemetry answers "what is the habitat doing". Some questions are not telemetry
at all — what the emergency numbers are, what the procedure for a pressure drop
is, who is on call. Those live in documents, and this package is how they become
answerable:

    extract.py   an uploaded PDF/Word/CSV/text file -> plain text
    chunk.py     that text -> passages small enough to retrieve
    embed.py     passages -> vectors, locally, via Ollama (lexical if no model)
    store.py     saving, indexing, connecting and forgetting documents
    search.py    a question -> the passages that answer it

Everything stays on this machine: the file under KNOWLEDGE_DIR, the passages in
the same SQLite database as the chat history, the embeddings from the local
model runtime. Nothing is uploaded anywhere.

The model reaches it through one tool, `search_knowledge`, offered only when a
document is actually connected. The grounding rules are unchanged: it may quote
what a passage says and must name the document, and it may not fill a gap the
documents do not cover.
"""
