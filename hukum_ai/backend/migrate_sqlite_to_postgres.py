import sqlite3
from db import SessionLocal, init_db, LawArticle

SQLITE_PATH = "traffic_law.db"


def main():
    print(f"Membaca data dari SQLite: {SQLITE_PATH}")

    conn = sqlite3.connect(SQLITE_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("""
        SELECT
            uu,
            pasal,
            title,
            legal_text,
            explanation,
            status,
            keywords_json
        FROM law_articles
    """)
    rows = cur.fetchall()
    print(f"Jumlah baris di SQLite law_articles: {len(rows)}")

    init_db()

    db = SessionLocal()

    try:
        existing = db.query(LawArticle).count()
        print(f"Jumlah baris di PostgreSQL law_articles sebelum migrasi: {existing}")

        if existing > 0:
            print("Tabel law_articles di PostgreSQL sudah berisi data.")
            print("Skrip tidak akan meng-insert lagi supaya tidak dobel.")
            return

        for i, r in enumerate(rows, start=1):
            art = LawArticle(
                uu=r["uu"],
                pasal=r["pasal"],
                title=r["title"],
                legal_text=r["legal_text"],
                explanation=r["explanation"],
                status=r["status"],
                keywords_json=r["keywords_json"],
            )
            db.add(art)

            if i % 50 == 0:
                print(f"  → Sudah menyiapkan {i} baris untuk di-insert...")

        db.commit()
        print("Commit ke PostgreSQL selesai.")

        total_after = db.query(LawArticle).count()
        print(f"Jumlah baris di PostgreSQL law_articles setelah migrasi: {total_after}")

    finally:
        db.close()
        conn.close()
        print("Koneksi ke SQLite dan PostgreSQL ditutup.")


if __name__ == "__main__":
    main()