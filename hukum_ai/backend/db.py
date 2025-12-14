import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

# Coba pakai DATABASE_URL langsung (misalnya dari Railway)
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    # fallback: untuk local development
    POSTGRES_USER = os.getenv("POSTGRES_USER", "hukum_ai_user")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "passwordku")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "hukum_ai_db")
    POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")

    DATABASE_URL = (
        f"postgresql+psycopg2://{POSTGRES_USER}:{POSTGRES_PASSWORD}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

engine = create_engine(DATABASE_URL, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db():
    from models import (
        LawArticle,
        SystemMeta,
        ChatSession,
        ChatMessage,
        User,
        PasswordResetToken,
    )

    Base.metadata.create_all(bind=engine)