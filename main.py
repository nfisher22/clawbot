import os
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI
import chromadb
from chromadb.config import Settings
from tavily import TavilyClient
from llm_client import chat_with_fallback

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODEL_NAME = os.getenv("MODEL_NAME", "gpt-4o-mini")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY")

DATA_DIR = Path("/opt/clawbot/data")
CHROMA_DIR = "/opt/clawbot/chroma_db"

client = OpenAI(api_key=OPENAI_API_KEY)
tavily = TavilyClient(api_key=TAVILY_API_KEY)

chroma_client = chromadb.PersistentClient(
    path=CHROMA_DIR,
    settings=Settings(anonymized_telemetry=False)
)

collection = chroma_client.get_or_create_collection(name="nate_brain")

def load_text_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

def load_system_context() -> str:
    system_prompt = load_text_file(DATA_DIR / "SYSTEM_PROMPT.md")
    profile = load_text_file(DATA_DIR / "PROFILE.md")
    ea_workflow = load_text_file(DATA_DIR / "EA_WORKFLOW.md")
    memory = load_memory_context()
    return f"{system_prompt}\n\nUser Profile:\n{profile}\n\nEA Workflow:\n{ea_workflow}\n\nMemory Context:\n{memory}".strip()


MEMORY_DIR = Path("/root/.openclaw/workspace-hatfield/memory")

def load_memory_context() -> str:
    """Load MEMORY.md + today's daily log for session startup context."""
    today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
    parts = []
    # Load MEMORY.md
    memory_file = MEMORY_DIR / "MEMORY.md"
    if memory_file.exists():
        parts.append("## Long-Term Memory\n" + memory_file.read_text(errors="ignore")[:2000])
    # Load today's daily log
    daily_log = MEMORY_DIR / f"{today}.md"
    if daily_log.exists():
        lines = daily_log.read_text(errors="ignore").strip().split("\n")
        recent = "\n".join(lines[-30:])
        parts.append(f"## Today's Activity ({today})\n" + recent)
    return "\n\n".join(parts)


# Quick loader — preload recent vectors at startup
_quick_cache = []

def quick_load_vectors(n=10):
    """Preload the most recent n vectors from ChromaDB into memory cache."""
    global _quick_cache
    try:
        results = collection.get(limit=n, include=["documents", "metadatas"])
        _quick_cache = list(zip(
            results.get("documents", []),
            results.get("metadatas", [])
        ))
        print(f"[quick_loader] Preloaded {len(_quick_cache)} vectors into cache")
    except Exception as e:
        print(f"[quick_loader] Failed to preload vectors: {e}")
        _quick_cache = []

def get_cached_context(query: str) -> str:
    """Return quick cache as context string — used before full vector search."""
    if not _quick_cache:
        return ""
    lines = []
    for doc, meta in _quick_cache[:5]:
        source = meta.get("source", "unknown") if meta else "unknown"
        lines.append(f"[{source}]: {doc[:200]}")
    return "\n".join(lines)

def get_embedding(text: str):
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return response.data[0].embedding

def search_brain(query: str, n_results: int = 5):
    embedding = get_embedding(query)
    results = collection.query(query_embeddings=[embedding], n_results=n_results, include=["documents", "metadatas"])
    chunks = []
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        source = meta.get("source", "unknown")
        chunks.append(f"FILE: {source}\nCONTENT:\n{doc}\n")
    return "\n---\n".join(chunks)

def needs_web_search(query: str) -> bool:
    keywords = ["today", "current", "latest", "news", "price", "weather", "right now", "this week", "stock", "score", "who won"]
    return any(k in query.lower() for k in keywords)

def search_web(query: str) -> str:
    results = tavily.search(query)
    output = []
    for r in results.get("results", [])[:3]:
        output.append(f"SOURCE: {r['url']}\n{r['content']}\n")
    return "\n---\n".join(output)

def chat(history: list, user_input: str) -> str:
    system_context = load_system_context()
    if needs_web_search(user_input):
        context = "WEB SEARCH RESULTS:\n" + search_web(user_input)
    else:
        context = "RELEVANT BRAIN CONTEXT:\n" + search_brain(user_input)
    system_message = f"{system_context}\n\n{context}"
    history.append({"role": "user", "content": user_input})
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=[{"role": "system", "content": system_message}] + history
    )
    output = response.choices[0].message.content
    history.append({"role": "assistant", "content": output})
    return output

def main():
    print("ClawBot V1.2 Brain + Web Mode is live. Type 'exit' to quit.\n")
    history = []
    while True:
        user_input = input("You: ").strip()
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        try:
            output = chat(history, user_input)
            print(f"\nClawBot>\n{output}\n")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    main()
