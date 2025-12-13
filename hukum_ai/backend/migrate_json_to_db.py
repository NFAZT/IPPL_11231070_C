import json
from pathlib import Path

from db import SessionLocal, init_db, LawArticle

BASE_DIR = Path(__file__).resolve().parent
JSON_PATH = BASE_DIR / "data" / "traffic_law_knowledge.json"


def main():
    init_db()

    with JSON_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    db = SessionLocal()

    try:
        db.query(LawArticle).delete()

        for item in data:
            art = LawArticle(
                id=item.get("id"),
                uu=item.get("uu", "UU 22 Tahun 2009"),
                pasal=item.get("pasal", ""),
                category=item.get("category", ""),
                title=item.get("title", ""),
                legal_text=item.get("legal_text", ""),
                explanation=item.get("explanation", ""),
                status="berlaku",
            )
            keywords = item.get("keywords") or []
            art.set_keywords(keywords)

            db.add(art)

        db.commit()
        print(f"Berhasil migrasi {len(data)} entri ke database.")
    finally:
        db.close()


if __name__ == "__main__":
    main()