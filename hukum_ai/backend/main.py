import os
import json
import re
import sys
import asyncio
import secrets
import urllib.request
import urllib.error
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, constr, ConfigDict
from dotenv import load_dotenv
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

KNOWLEDGE_PATH = BASE_DIR / "data" / "traffic_law_knowledge.json"
TRAIN_PATH = BASE_DIR / "data" / "question_train_data.json"

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.1"))

INTENT_SIM_THRESHOLD = float(os.getenv("INTENT_SIM_THRESHOLD", "0.25"))

GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "false").lower() in ("1", "true", "yes", "y", "on")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or ""
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_TIMEOUT_SECONDS = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "12"))

CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
if CORS_ALLOW_ORIGINS == "*":
    ALLOW_ORIGINS = ["*"]
else:
    ALLOW_ORIGINS = [o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()]

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def tokenize(text: str) -> List[str]:
    return [w for w in re.findall(r"[a-zA-Z0-9]+", (text or "").lower()) if len(w) > 2]

def load_json_list(path: Path) -> List[Dict[str, Any]]:
    try:
        with path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return []
    except Exception as e:
        print(f"[WARNING] Gagal load JSON {path}: {e}")
        return []
    if isinstance(raw, dict):
        return [raw]
    if isinstance(raw, list):
        return raw
    return []

INDEX: List[Dict[str, Any]] = []
TRAIN_EXAMPLES: List[Dict[str, Any]] = []

def build_index_from_knowledge_file() -> List[Dict[str, Any]]:
    raw = load_json_list(KNOWLEDGE_PATH)
    if not raw:
        print(f"[WARNING] Knowledge file kosong / tidak ada: {KNOWLEDGE_PATH}")
        return []

    index: List[Dict[str, Any]] = []
    for item in raw:
        uu = item.get("uu") or ""
        pasal = item.get("pasal") or ""
        title = item.get("title") or ""
        legal_text = item.get("legal_text") or ""
        explanation = item.get("explanation") or ""
        keywords = item.get("keywords") or []

        judul = f"{uu} - {pasal}: {title}".strip(" -:")
        parts = []
        if legal_text:
            parts.append(legal_text)
        if explanation:
            parts.append(explanation)
        if keywords:
            parts.append("Keyword: " + ", ".join(keywords))
        isi = "\n".join(parts).strip()

        tokens = tokenize(isi + " " + " ".join(keywords))

        index.append(
            {
                "id": str(item.get("id", "")) or f"file:{uu}:{pasal}:{title}",
                "judul": judul,
                "isi": isi,
                "uu": uu,
                "pasal": pasal,
                "title": title,
                "legal_text": legal_text,
                "explanation": explanation,
                "keywords": keywords,
                "tokens": tokens,
                "source": "file",
            }
        )
    print(f"[RAG] Loaded {len(index)} dokumen dari file {KNOWLEDGE_PATH}")
    return index

def build_index_from_db(db: Session) -> List[Dict[str, Any]]:
    try:
        rows = (
            db.query(LawArticle)
            .filter(LawArticle.status == "berlaku")
            .order_by(LawArticle.id.asc())
            .all()
        )
    except Exception as e:
        print(f"[WARNING] Gagal query LawArticle untuk index: {e}")
        return []

    index: List[Dict[str, Any]] = []
    for a in rows:
        uu = getattr(a, "uu", "") or ""
        pasal = getattr(a, "pasal", "") or ""
        title = getattr(a, "title", "") or ""
        legal_text = getattr(a, "legal_text", "") or ""
        explanation = getattr(a, "explanation", "") or ""

        keywords: List[str] = []
        if hasattr(a, "get_keywords"):
            try:
                keywords = a.get_keywords() or []
            except Exception:
                keywords = []

        judul = f"{uu} - {pasal}: {title}".strip(" -:")
        parts = []
        if legal_text:
            parts.append(legal_text)
        if explanation:
            parts.append(explanation)
        if keywords:
            parts.append("Keyword: " + ", ".join(keywords))
        isi = "\n".join(parts).strip()

        tokens = tokenize(isi + " " + " ".join(keywords))

        index.append(
            {
                "id": f"db:{a.id}",
                "judul": judul,
                "isi": isi,
                "uu": uu,
                "pasal": pasal,
                "title": title,
                "legal_text": legal_text,
                "explanation": explanation,
                "keywords": keywords,
                "tokens": tokens,
                "source": "db",
            }
        )
    print(f"[RAG] Loaded {len(index)} dokumen dari DB LawArticle (status=berlaku)")
    return index

def rebuild_runtime_index(db: Optional[Session] = None) -> int:
    global INDEX
    docs = []
    docs.extend(build_index_from_knowledge_file())
    if db is not None:
        docs.extend(build_index_from_db(db))

    seen = set()
    unique_docs = []
    for d in docs:
        key = (d.get("uu", ""), d.get("pasal", ""), d.get("title", ""), d.get("legal_text", ""))
        if key in seen:
            continue
        seen.add(key)
        unique_docs.append(d)

    INDEX = unique_docs
    return len(INDEX)

def load_training_examples() -> List[Dict[str, Any]]:
    raw = load_json_list(TRAIN_PATH)
    if not raw:
        print(f"[INTENT] Training file kosong / tidak ada: {TRAIN_PATH}")
        return []
    examples: List[Dict[str, Any]] = []
    for item in raw:
        q = (item.get("question") or "").strip()
        intent = (item.get("intent") or item.get("label") or "").strip()
        if not q or not intent:
            continue
        examples.append(
            {
                "question": q,
                "intent": intent,
                "tokens": tokenize(q),
            }
        )
    print(f"[INTENT] Loaded {len(examples)} training examples dari {TRAIN_PATH}")
    return examples

def is_traffic_related(question: str) -> bool:
    q = (question or "").lower()
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

def intent_rule_based(question: str) -> Optional[str]:
    q = (question or "").lower()
    hukum_keywords = [
        "pasal",
        "undang-undang",
        "uu ",
        "uu no",
        "uu nomor",
        "berapa denda",
        "dendanya berapa",
        "sanksi apa",
        "hukuman apa",
        "ancaman pidana",
        "pidananya apa",
        "ayat",
    ]
    if any(kw in q for kw in hukum_keywords):
        return "butuh_pasal"
    return None

def best_intent_from_training(question: str) -> Optional[str]:
    if not TRAIN_EXAMPLES:
        return None

    q_tokens = tokenize(question)
    if not q_tokens:
        return None

    q_set = set(q_tokens)
    best_score = 0.0
    best_intent = None

    for ex in TRAIN_EXAMPLES:
        t = ex.get("tokens") or []
        if not t:
            continue
        t_set = set(t)
        inter = len(q_set & t_set)
        if inter == 0:
            continue
        score = inter / max(1, len(q_set))
        if score > best_score:
            best_score = score
            best_intent = ex.get("intent")

    if best_intent and best_score >= INTENT_SIM_THRESHOLD:
        return best_intent
    return None

def predict_intent(question: str) -> str:
    rule = intent_rule_based(question)
    if rule:
        return rule
    trained = best_intent_from_training(question)
    if trained:
        return trained
    return "tips_umum"

def search_top_k(question: str, k: int = 3, min_score: float = 0.1) -> List[Dict[str, Any]]:
    if not INDEX:
        return []
    q_tokens = tokenize(question)
    if not q_tokens:
        return []

    q_set = set(q_tokens)
    scored: List[tuple[float, Dict[str, Any]]] = []

    for doc in INDEX:
        tokens = doc.get("tokens") or []
        if not tokens:
            tokens = tokenize(doc.get("isi", ""))
            doc["tokens"] = tokens
        t_set = set(tokens)
        overlap = len(q_set & t_set)
        if overlap == 0:
            continue

        kw_overlap = 0
        for kw in doc.get("keywords") or []:
            kw_tokens = set(tokenize(kw))
            kw_overlap += len(q_set & kw_tokens)

        base = overlap / max(1, len(q_set))
        score = base + 0.3 * kw_overlap
        if score > 0:
            scored.append((score, doc))

    scored.sort(key=lambda x: x[0], reverse=True)
    top_docs: List[Dict[str, Any]] = []
    for s, d in scored[:k]:
        if s >= min_score:
            doc_copy = dict(d)
            doc_copy["score"] = float(s)
            top_docs.append(doc_copy)

    return top_docs

def detect_tone(question: str) -> str:
    q = (question or "").lower()
    slang_words = ["ga", "gak", "gk", "nggak", "ngga", "lu", "lo", "loe", "bro", "bray", "wkwk", "haha", "hehe"]
    if any(w in q for w in slang_words):
        return "santai"
    return "formal"

def shorten(text: str, max_len: int = 400) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    last_space = cut.rfind(" ")
    if last_space > 100:
        cut = cut[:last_space]
    return cut.rstrip() + "..."

def generate_answer(question: str, docs: List[Dict[str, Any]], tone: str, intent: str) -> str:
    if not docs:
        if tone == "santai":
            return "Maaf, untuk pertanyaan ini aku belum menemukan pasal yang benar-benar cocok di basis data. Yang penting tetap patuhi rambu, jaga kecepatan, dan utamakan keselamatan, ya."
        return "Maaf, untuk pertanyaan tersebut saya belum menemukan pasal yang spesifik di basis data. Sebaiknya tetap mematuhi rambu, marka, dan instruksi petugas demi keselamatan."

    doc = docs[0]
    uu = doc.get("uu") or "peraturan lalu lintas yang berlaku"
    pasal = doc.get("pasal") or ""
    title = doc.get("title") or ""
    legal_text = doc.get("legal_text") or ""
    explanation = doc.get("explanation") or ""

    legal_short = shorten(legal_text, 500)
    expl_short = shorten(explanation, 500)

    if tone == "santai":
        pembuka = "Secara singkat, begini ya:\n\n"
        subjek = "kamu"
    else:
        pembuka = "Secara singkat, penjelasannya sebagai berikut:\n\n"
        subjek = "Anda"

    if intent == "butuh_pasal":
        bagian1 = f"Menurut {uu}"
        if pasal:
            bagian1 += f" {pasal}"
        if title:
            bagian1 += f", tentang {title}."
        else:
            bagian1 += "."
        if legal_short:
            bagian1 += f" Ketentuannya kurang lebih berbunyi seperti ini:\n{legal_short}"
        if expl_short:
            bagian2 = f"\n\nDalam praktiknya, maknanya untuk {subjek} adalah:\n{expl_short}"
        else:
            bagian2 = ""
        ringkas = "\n\nIntinya, {subjek} perlu mematuhi ketentuan ini agar terhindar dari sanksi dan menjaga keselamatan di jalan.".replace(
            "{subjek}", subjek
        )
        return pembuka + bagian1 + bagian2 + ringkas

    bagian1 = ""
    if title:
        bagian1 = f"{title} diatur dalam {uu}"
        if pasal:
            bagian1 += f" {pasal}."
        else:
            bagian1 += "."
    else:
        bagian1 = f"Hal ini diatur dalam {uu}"
        if pasal:
            bagian1 += f" {pasal}."
        else:
            bagian1 += "."

    if expl_short:
        bagian2 = f"\n\nSecara sederhana, maknanya untuk {subjek} adalah:\n{expl_short}"
    elif legal_short:
        bagian2 = f"\n\nJika disederhanakan, isi aturannya untuk {subjek} kira-kira seperti ini:\n{legal_short}"
    else:
        bagian2 = "\n\nAturannya menekankan pentingnya tertib berlalu lintas dan mengutamakan keselamatan semua pengguna jalan."

    ringkas = "\n\nSingkatnya, patuhi aturan ini supaya perjalanan tetap aman dan terhindar dari masalah hukum."
    return pembuka + bagian1 + bagian2 + ringkas

def build_gemini_prompt(question: str, intent: str, tone: str, docs: List[Dict[str, Any]]) -> str:
    style = "Bahasa Indonesia santai tapi sopan." if tone == "santai" else "Bahasa Indonesia sopan dan jelas."
    if intent == "butuh_pasal":
        instruction = (
            "Jawab pertanyaan berdasarkan konteks pasal/peraturan di bawah. "
            "Kalau konteks kurang, bilang tidak menemukan pasal yang tepat dan sarankan user memperjelas."
        )
    else:
        instruction = (
            "Jawab pertanyaan dengan penjelasan praktis dan aman, tetap berdasarkan konteks di bawah. "
            "Kalau konteks kurang, berikan saran umum keselamatan berkendara tanpa mengarang pasal."
        )

    ctx_lines = []
    for i, d in enumerate(docs[:3], start=1):
        judul = d.get("judul", "")
        isi = shorten(d.get("isi", ""), 900)
        ctx_lines.append(f"[Sumber {i}] {judul}\n{isi}")

    context = "\n\n".join(ctx_lines).strip()
    if not context:
        context = "(Tidak ada konteks pasal yang ditemukan)"

    return (
        f"{instruction}\n"
        f"Gaya bahasa: {style}\n\n"
        f"KONTEKS:\n{context}\n\n"
        f"PERTANYAAN USER:\n{question}\n"
    )

def gemini_generate_text(prompt: str, api_key: str, model: str, timeout_seconds: float) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [
            {"role": "user", "parts": [{"text": prompt}]}
        ]
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8")
        except Exception:
            body = ""
        raise RuntimeError(f"Gemini HTTPError {e.code}: {body[:300]}") from e
    except Exception as e:
        raise RuntimeError(f"Gemini request failed: {e}") from e

    try:
        parsed = json.loads(raw)
    except Exception as e:
        raise RuntimeError(f"Gemini response not JSON: {raw[:300]}") from e

    candidates = parsed.get("candidates") or []
    for cand in candidates:
        content = cand.get("content") or {}
        parts = content.get("parts") or []
        texts = [p.get("text") for p in parts if isinstance(p, dict) and p.get("text")]
        if texts:
            return "\n".join(texts).strip()

    raise RuntimeError("Gemini response empty")

app = FastAPI(
    title="Hukum Lalu Lintas Chatbot (RAG + Optional Gemini)",
    description="Backend chatbot hukum lalu lintas dengan knowledge base lokal + fallback kalau Gemini gagal",
)

@app.on_event("startup")
def on_startup():
    print("[STARTUP] init_db() dipanggil")
    init_db()

    global TRAIN_EXAMPLES
    TRAIN_EXAMPLES = load_training_examples()

    try:
        db = SessionLocal()
        total = rebuild_runtime_index(db)
        print(f"[STARTUP] Runtime RAG index built. total_docs={total}")
    except Exception as e:
        print(f"[WARNING] Gagal build index saat startup: {e}")
    finally:
        try:
            db.close()
        except Exception:
            pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=False if ALLOW_ORIGINS == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
async def chat(req: ChatRequest, db: Session = Depends(get_db)):
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
            candidate = db.get(ChatSession, req.session_id)
            if candidate and candidate.username == username:
                session_obj = candidate

        if session_obj is None:
            session_obj = ChatSession(
                username=username,
                title=question[:120],
            )
            db.add(session_obj)
            db.commit()
            db.refresh(session_obj)

    intent = predict_intent(question)
    session_id_for_log = session_obj.id if session_obj else None
    print(f"[CHAT] intent={intent} session={session_id_for_log} user={username or '-'} gemini={GEMINI_ENABLED}")

    docs: List[Dict[str, Any]] = search_top_k(question, k=RAG_TOP_K, min_score=RAG_MIN_SCORE)

    if not docs and not is_traffic_related(question):
        answer_text = (
            "Maaf, aku cuma bisa bantu pertanyaan yang masih berkaitan "
            "dengan lalu lintas dan hukum lalu lintas di Indonesia. "
            "Coba ubah pertanyaannya supaya tetap dalam topik lalu lintas, ya."
        )
        sources_with_score: List[SourceDoc] = []
    else:
        tone = detect_tone(question)

        rag_answer = generate_answer(question, docs, tone=tone, intent=intent)
        answer_text = rag_answer

        if GEMINI_ENABLED and GEMINI_API_KEY and is_traffic_related(question):
            try:
                prompt = build_gemini_prompt(question, intent=intent, tone=tone, docs=docs)
                gemini_text = await asyncio.to_thread(
                    gemini_generate_text,
                    prompt,
                    GEMINI_API_KEY,
                    GEMINI_MODEL,
                    GEMINI_TIMEOUT_SECONDS,
                )
                if gemini_text and gemini_text.strip():
                    answer_text = gemini_text.strip()
                    print("[GEMINI] success")
            except Exception as e:
                print(f"[GEMINI] failed -> fallback to RAG. err={e}")

        sources_with_score = []
        if intent == "butuh_pasal":
            for d in docs:
                sources_with_score.append(
                    SourceDoc(
                        id=str(d.get("id", "")),
                        judul=d.get("judul", ""),
                        isi=d.get("isi", ""),
                        score=float(d.get("score", 0.0)),
                    )
                )

    if not is_guest and session_obj is not None:
        try:
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
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Gagal menyimpan riwayat chat: {e}")

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
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing_username = db.query(User).filter(User.username == payload.username).first()
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
def login(payload: LoginRequest, db: Session = Depends(get_db)):
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
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
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

    return SimpleMessageResponse(message="Jika email terdaftar, tautan reset password telah dikirim.")

@app.post("/auth/reset-password", response_model=SimpleMessageResponse)
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
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
def create_article(payload: LawArticleCreate, db: Session = Depends(get_db)):
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
def update_article(article_id: int, payload: LawArticleUpdate, db: Session = Depends(get_db)):
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
def delete_article(article_id: int, db: Session = Depends(get_db)):
    article = db.get(LawArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Pasal tidak ditemukan")

    db.delete(article)
    db.commit()

    return {"detail": "Pasal berhasil dihapus"}

@app.get("/articles/{article_id}", response_model=LawArticleOut)
def get_article(article_id: int, db: Session = Depends(get_db)):
    article = db.get(LawArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Pasal tidak ditemukan")
    return article_to_schema(article)

@app.get("/articles", response_model=List[LawArticleOut])
def list_articles(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(LawArticle).order_by(LawArticle.id).limit(limit).all()
    return [article_to_schema(a) for a in rows]

@app.post("/admin/rebuild-index")
def admin_rebuild_index(db: Session = Depends(get_db)):
    try:
        total = rebuild_runtime_index(db)
        now = datetime.now(timezone.utc).isoformat()
        meta = db.query(SystemMeta).filter(SystemMeta.key == "rag_index_last_built_at").first()
        if meta is None:
            meta = SystemMeta(key="rag_index_last_built_at", value=now)
            db.add(meta)
        else:
            meta.value = now
        db.commit()

        return {
            "detail": "Index berhasil dibangun ulang",
            "indexed_documents": total,
            "knowledge_path": str(KNOWLEDGE_PATH),
            "train_path": str(TRAIN_PATH),
            "last_built_at": now,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gagal membangun ulang index: {e}")

@app.get("/admin/index-status")
def admin_index_status(db: Session = Depends(get_db)):
    meta = db.query(SystemMeta).filter(SystemMeta.key == "rag_index_last_built_at").first()
    return {
        "last_built_at": meta.value if meta else None,
        "indexed_documents": len(INDEX),
        "training_examples": len(TRAIN_EXAMPLES),
        "gemini_enabled": GEMINI_ENABLED,
        "gemini_model": GEMINI_MODEL,
    }

@app.get("/chat-history/{username}", response_model=List[ChatSessionSummary])
def get_chat_history(username: str, db: Session = Depends(get_db)):
    rows = (
        db.query(ChatSession)
        .filter(ChatSession.username == username)
        .order_by(ChatSession.updated_at.desc())
        .all()
    )
    return [session_to_summary(s) for s in rows]

@app.get("/chat-sessions/{session_id}", response_model=ChatSessionDetail)
def get_chat_session_detail(session_id: int, db: Session = Depends(get_db)):
    session_obj = db.get(ChatSession, session_id)
    if not session_obj:
        raise HTTPException(status_code=404, detail="Sesi konsultasi tidak ditemukan")

    msgs_sorted = sorted(session_obj.messages or [], key=lambda m: m.created_at)

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
    debug = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=debug)