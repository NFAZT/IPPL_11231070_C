from sqlalchemy import text
from db import init_db, SessionLocal
from models import LawArticle

def main():
    print("Inisialisasi database (create_all)...")
    init_db()

    db = SessionLocal()
    try:
        result = db.execute(text("SELECT 1"))
        print("Hasil SELECT 1:", result.scalar())

        count = db.query(LawArticle).count()
        print("Jumlah baris di tabel law_articles:", count)
    finally:
        db.close()

if __name__ == "__main__":
    main()