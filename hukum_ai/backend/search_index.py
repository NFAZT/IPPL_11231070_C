import os
import json
import math
from typing import List, Dict, Any
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY atau GOOGLE_API_KEY belum di-set")

client = genai.Client(api_key=api_key)

EMBED_MODEL = "gemini-embedding-001"
INDEX_PATH = "data/traffic_law_index.json"

with open(INDEX_PATH, "r", encoding="utf-8") as f:
    INDEX: List[Dict[str, Any]] = json.load(f)

EMBEDDINGS = [doc["embedding"] for doc in INDEX]


def embed_text(text: str) -> List[float]:
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=text,
    )
    return result.embeddings[0].values


def cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
    dot = 0.0
    norm1 = 0.0
    norm2 = 0.0
    for a, b in zip(vec1, vec2):
        dot += a * b
        norm1 += a * a
        norm2 += b * b
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


def search_similar(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    q_vec = embed_text(query)

    scored_docs = []
    for doc, emb in zip(INDEX, EMBEDDINGS):
        score = cosine_similarity(q_vec, emb)
        d = dict(doc)  # copy
        d["score"] = score
        scored_docs.append(d)

    scored_docs.sort(key=lambda d: d["score"], reverse=True)
    return scored_docs[:top_k]