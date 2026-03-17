import os
from pathlib import Path
from vault_secrets import get_secrets
get_secrets()
from dotenv import load_dotenv
load_dotenv()
from openai import OpenAI
import chromadb
from chromadb.config import Settings

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBED_MODEL = os.getenv("EMBED_MODEL", "text-embedding-3-small")
CHROMA_DIR = "/opt/clawbot/chroma_db"
SUPPORTED_EXTENSIONS = {".md", ".txt", ".json", ".csv"}

BRAIN_DIR = Path("/opt/clawbot/AI_Brain")
MEMORY_DIR = Path("/root/.openclaw/workspace-hatfield/memory")
DATA_DIR = Path("/opt/clawbot/data")
INDEX_DIRS = [
    (BRAIN_DIR, "ai_brain"),
    (MEMORY_DIR, "daily_logs"),
    (DATA_DIR, "system_data"),
]

client = OpenAI(api_key=OPENAI_API_KEY)
chroma_client = chromadb.PersistentClient(
    path=CHROMA_DIR,
    settings=Settings(anonymized_telemetry=False)
)
collection = chroma_client.get_or_create_collection(name="nate_brain")

def load_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""

def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 150):
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start += max(1, chunk_size - overlap)
    return chunks

def get_embedding(text: str):
    response = client.embeddings.create(model=EMBED_MODEL, input=text)
    return response.data[0].embedding

def index_brain():
    ids, documents, metadatas, embeddings = [], [], [], []
    count = 0
    total_files = 0
    for base_dir, source_tag in INDEX_DIRS:
        if not base_dir.exists():
            print(f"Skipping missing dir: {base_dir}")
            continue
        for file_path in base_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            if any(skip in str(file_path) for skip in ["chroma_db", "venv", "__pycache__"]):
                continue
            total_files += 1
            text = load_text_file(file_path)
            if not text.strip():
                continue
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                chunk_id = f"{source_tag}::{file_path.name}::chunk_{i}"
                embedding = get_embedding(chunk)
                ids.append(chunk_id)
                documents.append(chunk)
                metadatas.append({
                    "source": f"{source_tag}/{file_path.name}",
                    "chunk_index": i
                })
                embeddings.append(embedding)
                count += 1
                if len(ids) >= 50:
                    collection.upsert(
                        ids=ids,
                        documents=documents,
                        metadatas=metadatas,
                        embeddings=embeddings
                    )
                    ids, documents, metadatas, embeddings = [], [], [], []
    if ids:
        collection.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas,
            embeddings=embeddings
        )
    print(f"Indexed {count} chunks from {total_files} files into Chroma.")

if __name__ == "__main__":
    index_brain()
