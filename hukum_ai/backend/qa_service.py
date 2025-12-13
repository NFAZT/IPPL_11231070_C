from typing import List, Dict, Any
from dotenv import load_dotenv
from google import genai
import os
from search_index import search_similar

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY atau GOOGLE_API_KEY belum di-set")

client = genai.Client(api_key=api_key)

GEN_MODEL = "gemini-1.5-flash"


def make_context_text(docs: List[Dict[str, Any]]) -> str:
    parts = []
    for d in docs:
        header = f"[{d['id']}] {d['judul']}"
        body = d["isi"]
        parts.append(f"{header}\n{body}")
    return "\n\n---\n\n".join(parts)


def answer_question(user_question: str) -> Dict[str, Any]:
    docs = search_similar(user_question, top_k=5)
    context = make_context_text(docs)

    system_instruction = (
        "Anda adalah asisten hukum lalu lintas Indonesia. "
        "Jawab pertanyaan pengguna hanya berdasarkan pasal-pasal yang diberikan di bawah. "
        "Jika tidak cukup informasi, katakan bahwa informasi tidak lengkap secara jelas, "
        "dan jangan mengarang pasal yang tidak ada."
    )

    prompt = (
        f"{system_instruction}\n\n"
        f"=== Konteks Pasal ===\n{context}\n\n"
        f"=== Pertanyaan Pengguna ===\n{user_question}\n\n"
        f"Berikan jawaban yang terstruktur dan mudah dipahami."
    )

    response = client.models.generate_content(
        model=GEN_MODEL,
        contents=prompt,
    )

    answer_text = response.text if hasattr(response, "text") else str(response)

    return {
        "answer": answer_text,
        "sources": [
            {"id": d["id"], "judul": d["judul"], "score": d["score"]}
            for d in docs
        ],
    }