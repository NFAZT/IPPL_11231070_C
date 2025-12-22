import os
import json
import math
import sys
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timezone, timedelta
import secrets
import joblib
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, constr, ConfigDict
from dotenv import load_dotenv
from google import genai
from sqlalchemy.orm import Session

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.append(str(BASE_DIR))

from db import SessionLocal, init_db
from models import (
    LawArticle,
    SystemMeta,
    ChatSession,
    ChatMessage,
    User,
    PasswordResetToken,
)
from security import hash_password, verify_password
from email_utils import send_password_reset_email

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
if not api_key:
    raise RuntimeError("GEMINI_API_KEY atau GOOGLE_API_KEY belum di-set di .env atau environment")

client = genai.Client(api_key=api_key)

EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL") or "gemini-embedding-001"
GEN_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
FALLBACK_MODELS_RAW = os.getenv("GEMINI_FALLBACK_MODELS") or "gemini-1.5-flash"
FALLBACK_MODELS = [m.strip() for m in FALLBACK_MODELS_RAW.split(",") if m.strip()]
GEN_MODELS = [GEN_MODEL] + [m for m in FALLBACK_MODELS if m != GEN_MODEL]

INDEX_PATH = BASE_DIR / "data" / "traffic_law_index.json"
INTENT_MODEL_PATH = BASE_DIR / "data" / "intent_model.joblib"

try:
    with INDEX_PATH.open(encoding="utf-8") as f:
        INDEX: List[Dict[str, Any]] = json.load(f)
except FileNotFoundError:
    print(f"[WARNING] INDEX file tidak ditemukan: {INDEX_PATH}. RAG akan jalan tanpa konteks.")
    INDEX = []

try:
    INTENT_MODEL = joblib.load(INTENT_MODEL_PATH)
except Exception as e:
    print(f"[WARNING] Gagal memuat intent model dari {INTENT_MODEL_PATH}: {e}")
    INTENT_MODEL = None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def embed_text(text: str) -> List[float]:
    result = client.models.embed_content(
        model=EMBED_MODEL,
        contents=text,
    )
    return result.embeddings[0].values

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (norm1 * norm2)

def is_traffic_related(question: str) -> bool:
    q = question.lower()
    keywords = [
        "lalu lintas",
        "angkutan jalan",
        "jalan raya",
        "jalan tol",
        "helm",
        "sabuk pengaman",
        "motor",
        "mobil",
        "kendaraan",
        "sim",
        "stnk",
        "tilang",
        "ngebut",
        "batas kecepatan",
        "rambu",
        "lampu merah",
        "polisi lalu lintas",
        "pengemudi",
        "penumpang",
        "berkendara",
    ]
    return any(kw in q for kw in keywords)

def search_top_k(
    query_embedding: List[float],
    k: int = 3,
    min_score: float = 0.3,
) -> List[Dict[str, Any]]:
    if not INDEX:
        return []
    if not query_embedding:
        return []
    scored: List[tuple[float, Dict[str, Any]]] = []
    for doc in INDEX:
        score = cosine_similarity(query_embedding, doc["embedding"])
        scored.append((score, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_docs = [d for s, d in scored[:k] if s >= min_score]
    return top_docs

def predict_intent(question: str) -> str:
    if INTENT_MODEL is None:
        return "tips_umum"
    try:
        return str(INTENT_MODEL.predict([question])[0])
    except Exception:
        return "tips_umum"

def build_context(docs: List[Dict[str, Any]]) -> str:
    if not docs:
        return "Tidak ada konteks dokumen yang relevan ditemukan."
    parts = []
    for i, d in enumerate(docs, start=1):
        judul = d.get("judul", f"Dokumen {i}")
        isi = d.get("isi", "")
        parts.append(f"[{i}] {judul}\n{isi}")
    return "\n\n".join(parts)

def detect_tone(question: str) -> str:
    q = question.lower()
    slang_words = ["ga", "gak", "gk", "nggak", "ngga", "lu", "lo", "loe", "bro", "bray", "wkwk", "haha", "hehe"]
    if any(w in q for w in slang_words):
        return "santai"
    return "formal"

def _is_retryable_error(err: Exception) -> bool:
    s = str(err)
    sl = s.lower()
    if "resource_exhausted" in s or "429" in s or "quota" in sl:
        return True
    if "not_found" in s or "404" in s or "is not found for api version" in sl:
        return True
    if "unavailable" in sl or "503" in s or "504" in s or "deadline" in sl or "timeout" in sl:
        return True
    return False

def generate_answer(question: str, context: str, tone: str = "formal") -> str:
    if tone == "santai":
        style = """
GUNAKAN GAYA BAHASA:
- Bahasa Indonesia santai dan akrab, tapi tetap sopan.
- Boleh pakai kata seperti "kamu", "aja", "nggak", "kok" jika pertanyaan pengguna juga santai.
- JANGAN gunakan kata-kata seperti "bro", "bray", "lu", "loe", atau kata kasar/merendahkan.
- Hindari bercanda berlebihan; tetap fokus menjelaskan aturan dan alasan keselamatan dengan contoh sehari-hari.
"""
    else:
        style = """
GUNAKAN GAYA BAHASA:
- Bahasa Indonesia jelas dan cukup formal, mudah dipahami orang awam.
- Gunakan sapaan netral seperti "Anda" atau tanpa sapaan jika tidak perlu.
- JANGAN gunakan kata gaul seperti "bro", "lu", "gue", "wkwk", dan sejenisnya.
- Jawaban boleh hangat dan ramah, tapi tetap terasa rapi dan profesional.
"""

    prompt = f"""
Kamu adalah asisten yang paham hukum dan keselamatan lalu lintas di Indonesia.

{style}

TUJUAN:
- Jawab semua pertanyaan yang masih dalam lingkup lalu lintas dan hukum lalu lintas.
- Jika pertanyaan berkaitan dengan pelanggaran (misalnya tidak pakai helm, ngebut, melanggar rambu):
  - Jelaskan apakah itu pelanggaran menurut konteks.
  - Jika di konteks ada pasal/UU yang relevan, sebutkan secara singkat di dalam kalimat (nama UU dan pasal).
  - Tambahkan juga alasan keselamatan: kenapa aturan itu penting.
- Jika pertanyaan lebih bersifat umum/tips:
  - Fokus pada tips berkendara yang aman dan tertib.

JAWABAN UNTUK PERTANYAAN DEFINISI:
- Jika pertanyaan JELAS meminta pengertian/arti/definisi suatu istilah (misalnya mengandung frasa seperti "apa itu", "yang dimaksud dengan", "arti dari"):
  - Buat jawaban dalam dua paragraf pendek:
    1) Paragraf pertama menjelaskan secara ringkas menurut ketentuan hukum atau rumusan resminya.
    2) Paragraf kedua mengulang dengan bahasa yang sangat sederhana untuk orang awam.
  - JANGAN menulis label khusus seperti "Definisi hukum:" atau "Versi gampangnya:".

PERTANYAAN PENDEK:
- HANYA jika pertanyaan sangat pendek dan benar-benar ambigu (sekitar 1–3 kata tanpa konteks, misalnya "umur?", "gimana?", "boleh nggak?"):
  - Jangan langsung menyebut pasal/UU spesifik.
  - Jelaskan bahwa pertanyaan masih terlalu umum dan minta pengguna memperjelas.
  - Berikan satu contoh pertanyaan yang lebih spesifik.
- Selain kasus ini, JANGAN mengatakan bahwa pertanyaan terlalu umum.

BATASAN TENTANG SUMBER:
- Jangan membuat bagian khusus berjudul "Sumber:".
- Jika perlu menyebut dasar hukum, sebutkan maksimal 1–2 pasal yang paling relevan dan selipkan di dalam kalimat penjelasan.

RINGKASAN AKHIR:
- Setelah menjelaskan pokok-pokok jawaban, AKHIRI jawaban dengan SATU kalimat ringkas yang merangkum inti jawaban.

KONTEKS DOKUMEN:
{context}

PERTANYAAN PENGGUNA:
{question}

JAWABAN:
"""

    last_err: Exception | None = None
    for model in GEN_MODELS:
        try:
            result = client.models.generate_content(
                model=model,
                contents=prompt,
            )
            text = (result.text or "").strip()
            if text:
                return text
        except Exception as e:
            last_err = e
            print(f"[GEMINI] model_try={model} failed: {e}")
            if not _is_retryable_error(e):
                break
            continue
    raise last_err or RuntimeError("Gemini tidak mengembalikan jawaban")

app = FastAPI(
    title="Hukum Lalu Lintas Chatbot (RAG + Gemini)",
    description="Backend chatbot hukum lalu lintas dengan RAG manual dan Gemini",
)

CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
if CORS_ALLOW_ORIGINS == "*":
    allow_origins = ["*"]
else:
    allow_origins = [o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=False if allow_origins == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()

class ChatRequest(BaseModel):
    question: str
    username: str | None = None
    session_id: int | None = None

class SourceDoc(BaseModel):
    id: str
    judul: str
    isi: str
    score: float

class ChatResponse(BaseModel):
    answer: str
    sources: List[SourceDoc]
    session_id: int | None = None

PasswordStr = constr(min_length=8, max_length=128)
UsernameStr = constr(min_length=3, max_length=50)

class RegisterRequest(BaseModel):
    username: UsernameStr
    email: EmailStr
    password: PasswordStr
    full_name: str | None = None

class LoginRequest(BaseModel):
    identifier: str
    password: str

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: PasswordStr

class UserOut(BaseModel):
    id: int
    username: str
    email: EmailStr
    full_name: str | None = None
    is_active: bool
    model_config = ConfigDict(from_attributes=True)

class LoginResponse(BaseModel):
    user: UserOut

class SimpleMessageResponse(BaseModel):
    message: str

class LawArticleBase(BaseModel):
    uu: str
    pasal: str
    title: str | None = None
    legal_text: str | None = None
    explanation: str | None = None
    status: str = "berlaku"
    keywords: List[str] | None = None

class LawArticleCreate(LawArticleBase):
    pass

class LawArticleUpdate(BaseModel):
    uu: str | None = None
    pasal: str | None = None
    title: str | None = None
    legal_text: str | None = None
    explanation: str | None = None
    status: str | None = None
    keywords: List[str] | None = None

class LawArticleOut(LawArticleBase):
    id: int

def article_to_schema(article: LawArticle) -> LawArticleOut:
    kws = None
    if hasattr(article, "get_keywords"):
        kws = article.get_keywords()
    return LawArticleOut(
        id=article.id,
        uu=article.uu,
        pasal=article.pasal,
        title=article.title,
        legal_text=article.legal_text,
        explanation=article.explanation,
        status=article.status,
        keywords=kws,
    )

class ChatSessionSummary(BaseModel):
    id: int
    title: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    last_message_preview: str | None = None
    total_messages: int

class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime

class ChatSessionDetail(BaseModel):
    id: int
    username: str
    title: str | None = None
    created_at: datetime
    updated_at: datetime | None = None
    messages: List[ChatMessageOut]

def rebuild_index_from_db(db: Session) -> int:
    articles: List[LawArticle] = (
        db.query(LawArticle)
        .filter(LawArticle.status == "berlaku")
        .order_by(LawArticle.id)
        .all()
    )

    new_index: List[Dict[str, Any]] = []

    for art in articles:
        doc_id = str(art.id)
        judul = f"{art.uu} - {art.pasal}: {art.title or ''}"

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
            continue

        vec = embed_text(isi)

        new_index.append(
            {
                "id": doc_id,
                "judul": judul,
                "isi": isi,
                "embedding": vec,
            }
        )

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(new_index, f, ensure_ascii=False, indent=2)

    global INDEX
    INDEX = new_index

    return len(new_index)

def session_to_summary(session: ChatSession) -> ChatSessionSummary:
    messages = session.messages or []
    last_msg = None
    if messages:
        last_msg = max(
            messages,
            key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc),
        )

    preview = None
    if last_msg:
        text = last_msg.content.strip()
        preview = text[:180] + ("..." if len(text) > 180 else "")

    return ChatSessionSummary(
        id=session.id,
        title=session.title,
        created_at=session.created_at,
        updated_at=session.updated_at,
        last_message_preview=preview,
        total_messages=len(messages),
    )

def message_to_schema(msg: ChatMessage) -> ChatMessageOut:
    return ChatMessageOut(
        id=msg.id,
        role=msg.role,
        content=msg.content,
        created_at=msg.created_at,
    )

@app.get("/")
async def root():
    return {"status": "ok", "message": "Backend hukum lalu lintas siap."}

@app.post("/chat", response_model=ChatResponse)
async def chat(
    req: ChatRequest,
    db: Session = Depends(get_db),
):
    question = (req.question or "").strip()
    username_raw = (req.username or "").strip()

    is_guest = not username_raw
    username = username_raw

    if not question:
        return ChatResponse(
            answer="Silakan ajukan pertanyaan seputar lalu lintas atau hukum lalu lintas.",
            sources=[],
            session_id=req.session_id,
        )

    session_obj: ChatSession | None = None

    if not is_guest:
        if req.session_id:
            session_obj = db.get(ChatSession, req.session_id)

        if session_obj is None:
            session_obj = ChatSession(
                username=username,
                title=question[:120],
            )
            db.add(session_obj)
            db.commit()
            db.refresh(session_obj)

    words = question.split()
    if len(words) <= 2:
        intent = "tips_umum"
    else:
        intent = predict_intent(question)

    session_id_for_log = session_obj.id if session_obj else None
    print(f"[INTENT] {intent} | session={session_id_for_log} | user={username or '-'} | model={GEN_MODEL}")

    query_emb: List[float] = []
    try:
        query_emb = embed_text(question)
    except Exception as e:
        print(f"[EMBED] failed: {e}")
        query_emb = []

    docs = search_top_k(query_emb, k=3, min_score=0.3) if query_emb else []

    if not docs and not is_traffic_related(question):
        answer_text = (
            "Maaf, aku cuma bisa membantu pertanyaan yang masih berkaitan "
            "dengan lalu lintas dan hukum lalu lintas di Indonesia. "
            "Coba ubah pertanyaannya supaya tetap dalam topik lalu lintas, ya."
        )
        sources_with_score: List[SourceDoc] = []
    else:
        context_text = build_context(docs)
        tone = detect_tone(question)

        try:
            answer_text = generate_answer(question, context_text, tone=tone)
        except Exception as e:
            if _is_retryable_error(e):
                answer_text = "Layanan AI sedang penuh atau model belum tersedia untuk API key ini. Coba lagi sebentar atau ganti model."
            else:
                answer_text = "Terjadi kendala saat memproses jawaban AI. Silakan coba lagi."
            print(f"[GEMINI] failed_final: {e}")

        sources_with_score = []

        if intent == "butuh_pasal" and query_emb:
            for d in docs:
                score = cosine_similarity(query_emb, d["embedding"])
                sources_with_score.append(
                    SourceDoc(
                        id=str(d["id"]),
                        judul=d.get("judul", ""),
                        isi=d.get("isi", ""),
                        score=score,
                    )
                )

    if not is_guest and session_obj is not None:
        session_obj.updated_at = datetime.now(timezone.utc)

        user_msg = ChatMessage(
            session_id=session_obj.id,
            role="user",
            content=question,
        )
        bot_msg = ChatMessage(
            session_id=session_obj.id,
            role="assistant",
            content=answer_text,
        )
        db.add_all([user_msg, bot_msg])
        db.commit()

        return ChatResponse(
            answer=answer_text,
            sources=sources_with_score,
            session_id=session_obj.id,
        )

    return ChatResponse(
        answer=answer_text,
        sources=sources_with_score,
        session_id=None,
    )

@app.post("/auth/register", response_model=UserOut)
def register(
    payload: RegisterRequest,
    db: Session = Depends(get_db),
):
    existing_username = (
        db.query(User)
        .filter(User.username == payload.username)
        .first()
    )
    if existing_username:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username sudah dipakai. Silakan pilih username lain.",
        )

    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email sudah terdaftar.",
        )

    user = User(
        username=payload.username,
        email=payload.email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@app.post("/auth/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),
):
    ident = payload.identifier.strip()

    query = db.query(User)
    if "@" in ident:
        user = query.filter(User.email == ident).first()
    else:
        user = query.filter(User.username == ident).first()

    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Username/email atau password salah.",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akun tidak aktif.",
        )

    return LoginResponse(user=user)

@app.post("/auth/forgot-password", response_model=SimpleMessageResponse)
def forgot_password(
    payload: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(User.email == payload.email).first()

    if user:
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used == False,
        ).delete()

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        prt = PasswordResetToken(
            user_id=user.id,
            token=token,
            expires_at=expires_at,
            used=False,
        )
        db.add(prt)
        db.commit()

        try:
            send_password_reset_email(user.email, token)
        except Exception as e:
            print(f"[EMAIL] Error kirim email reset: {e}")

    return SimpleMessageResponse(
        message="Jika email terdaftar, tautan reset password telah dikirim.",
    )

@app.post("/auth/reset-password", response_model=SimpleMessageResponse)
def reset_password(
    payload: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    token_obj = db.query(PasswordResetToken).filter(
        PasswordResetToken.token == payload.token,
        PasswordResetToken.used == False,
    ).first()

    now = datetime.now(timezone.utc)

    if not token_obj or token_obj.expires_at < now:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token tidak valid atau sudah kadaluarsa.",
        )

    user = db.query(User).filter(User.id == token_obj.user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User tidak ditemukan.",
        )

    user.hashed_password = hash_password(payload.new_password)
    token_obj.used = True
    db.commit()

    return SimpleMessageResponse(message="Password berhasil direset.")

@app.post("/articles", response_model=LawArticleOut)
def create_article(
    payload: LawArticleCreate,
    db: Session = Depends(get_db),
):
    article = LawArticle(
        uu=payload.uu,
        pasal=payload.pasal,
        title=payload.title,
        legal_text=payload.legal_text,
        explanation=payload.explanation,
        status=payload.status,
    )

    if payload.keywords and hasattr(article, "set_keywords"):
        article.set_keywords(payload.keywords)

    db.add(article)
    db.commit()
    db.refresh(article)

    return article_to_schema(article)

@app.put("/articles/{article_id}", response_model=LawArticleOut)
def update_article(
    article_id: int,
    payload: LawArticleUpdate,
    db: Session = Depends(get_db),
):
    article = db.get(LawArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Pasal tidak ditemukan")

    data = payload.dict(exclude_unset=True)

    if "keywords" in data:
        keywords = data.pop("keywords")
        if keywords is not None and hasattr(article, "set_keywords"):
            article.set_keywords(keywords)

    for field, value in data.items():
        setattr(article, field, value)

    db.commit()
    db.refresh(article)

    return article_to_schema(article)

@app.delete("/articles/{article_id}")
def delete_article(
    article_id: int,
    db: Session = Depends(get_db),
):
    article = db.get(LawArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Pasal tidak ditemukan")

    db.delete(article)
    db.commit()

    return {"detail": "Pasal berhasil dihapus"}

@app.get("/articles/{article_id}", response_model=LawArticleOut)
def get_article(
    article_id: int,
    db: Session = Depends(get_db),
):
    article = db.get(LawArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Pasal tidak ditemukan")
    return article_to_schema(article)

@app.get("/articles", response_model=List[LawArticleOut])
def list_articles(
    limit: int = 50,
    db: Session = Depends(get_db),
):
    rows = db.query(LawArticle).order_by(LawArticle.id).limit(limit).all()
    return [article_to_schema(a) for a in rows]

@app.post("/admin/rebuild-index")
def admin_rebuild_index(
    db: Session = Depends(get_db),
):
    try:
        total = rebuild_index_from_db(db)
        now = datetime.now(timezone.utc).isoformat()
        meta = (
            db.query(SystemMeta)
            .filter(SystemMeta.key == "rag_index_last_built_at")
            .first()
        )
        if meta is None:
            meta = SystemMeta(key="rag_index_last_built_at", value=now)
            db.add(meta)
        else:
            meta.value = now
        db.commit()

        return {
            "detail": "Index berhasil dibangun ulang",
            "total_active_articles": total,
            "index_path": str(INDEX_PATH),
            "last_built_at": now,
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Gagal membangun ulang index: {e}",
        )

@app.get("/admin/index-status")
def admin_index_status(
    db: Session = Depends(get_db),
):
    meta = (
        db.query(SystemMeta)
        .filter(SystemMeta.key == "rag_index_last_built_at")
        .first()
    )
    return {
        "last_built_at": meta.value if meta else None,
        "indexed_documents": len(INDEX),
        "embed_model": EMBED_MODEL,
        "gen_model": GEN_MODEL,
        "fallback_models": GEN_MODELS,
    }

@app.get("/chat-history/{username}", response_model=List[ChatSessionSummary])
def get_chat_history(
    username: str,
    db: Session = Depends(get_db),
):
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.username == username)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return [session_to_summary(s) for s in rows]

@app.get("/chat-sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
):
    session_obj = db.get(ChatSession, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Sesi konsultasi tidak ditemukan")

    msgs_sorted = sorted(
        session_obj.messages or [],
        key=lambda m: m.created_at,
    )

    return ChatSessionDetail(
        id=session_obj.id,
        username=session_obj.username,
        title=session_obj.title,
        created_at=session_obj.created_at,
        updated_at=session_obj.updated_at,
        messages=[message_to_schema(m) for m in msgs_sorted],
    )

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )