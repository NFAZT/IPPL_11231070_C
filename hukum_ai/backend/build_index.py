import os
import json
import time
from typing import List, Dict, Any

from dotenv import load_dotenv
from google import genai
from google.genai import errors

from db import SessionLocal
from models import LawArticle

print("build_index.py DIJALANKAN (versi DB, dengan retry & resume")

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY atau GOOGLE_API_KEY belum di-set di .env atau environment")

client = genai.Client(api_key=api_key)

EMBED_MODEL = "gemini-embedding-001"

INDEX_PATH = "data/traffic_law_index.json"


def embed_text(text: str, max_retries: int = 5, base_wait: int = 30) -> List[float]:
    for attempt in range(max_retries):
        try:
            result = client.models.embed_content(
                model=EMBED_MODEL,
                contents=text,
            )
            return result.embeddings[0].values

        except errors.ClientError as e:
            if e.status_code == 429:
                wait = base_wait * (attempt + 1)
                print(
                    f"[WARN] Gemini rate limited (429), percobaan ke-{attempt + 1}. "
                    f"Tunggu {wait} detik lalu coba lagi..."
                )
                time.sleep(wait)
                continue
            else:
                print(f"[ERROR] ClientError dari Gemini (status={e.status_code}): {e}")
                raise

        except Exception as e:
            print(f"[ERROR] Error tak terduga saat embed: {e}")
            raise

    raise RuntimeError(f"Gagal embed teks setelah {max_retries} percobaan")


def load_existing_index() -> List[Dict[str, Any]]:
    if not os.path.exists(INDEX_PATH):
        return []

    try:
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[INFO] Index lama ditemukan: {len(data)} dokumen (akan dilanjutkan).")
        return data
    except Exception as e:
        print(f"[WARN] Gagal membaca index lama ({INDEX_PATH}): {e}")
        print("       Index akan dibangun ulang dari awal.")
        return []


def main():
    db = SessionLocal()

    articles: List[LawArticle] = db.query(LawArticle).filter(
        LawArticle.status == "berlaku"
    ).all()
    print(f"Total dokumen aktif di DB: {len(articles)}")

    index: List[Dict[str, Any]] = load_existing_index()
    existing_ids = {item["id"] for item in index}
    if existing_ids:
        print(f"[INFO] Dokumen yang sudah ter-index: {len(existing_ids)}")

    try:
        for i, art in enumerate(articles, start=1):
            doc_id = str(art.id)

            if doc_id in existing_ids:
                print(f"Lewati dokumen ke-{i} (id={doc_id}) karena sudah ada di index.")
                continue

            judul = f"{art.uu} - {art.pasal}: {art.title}"

            keywords = art.get_keywords() if hasattr(art, "get_keywords") else []
            legal_text = art.legal_text or ""
            explanation = art.explanation or ""

            isi_parts = []
            if legal_text:
                isi_parts.append(legal_text)
            if explanation:
                isi_parts.append(explanation)
            if keywords:
                isi_parts.append("Keyword: " + ", ".join(keywords))

            isi = "\n".join(isi_parts).strip()
            if not isi:
                print(f" [!] Dokumen id={doc_id} tidak punya isi, dilewati.")
                continue

            vec = embed_text(isi)

            index.append({
                "id": doc_id,
                "judul": judul,
                "isi": isi,
                "embedding": vec,
            })

            print(f"Sudah memproses dokumen ke-{i} (id={doc_id})")
            time.sleep(1)

    finally:
        db.close()

    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"Selesai membangun index. Total: {len(index)} dokumen → {INDEX_PATH}")


if __name__ == "__main__":
    main()