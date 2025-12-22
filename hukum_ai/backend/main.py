import os
import json
import math
import re
import sys
import time
import secrets
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, timezone, timedelta

from fastapi import FastAPI, Depends, HTTPException, status, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, constr, ConfigDict
from dotenv import load_dotenv
from sqlalchemy.orm import Session

try:
    from google import genai
except Exception:
    genai = None

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

API_KEY = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
GEMINI_ENABLED = os.getenv("GEMINI_ENABLED", "true").lower() in ("1", "true", "yes", "y", "on")
GEMINI_ENABLED = GEMINI_ENABLED and bool(API_KEY) and (genai is not None)

CLIENT = None
if GEMINI_ENABLED:
    try:
        CLIENT = genai.Client(api_key=API_KEY)
    except Exception:
        CLIENT = None
        GEMINI_ENABLED = False

EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL") or "gemini-embedding-001"
GEN_MODEL = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
FALLBACK_MODELS_RAW = os.getenv("GEMINI_FALLBACK_MODELS") or "gemini-2.0-flash,gemini-1.5-flash"
FALLBACK_MODELS = [m.strip() for m in FALLBACK_MODELS_RAW.split(",") if m.strip()]
GEN_MODELS = [GEN_MODEL] + [m for m in FALLBACK_MODELS if m != GEN_MODEL]

CORS_ALLOW_ORIGINS = os.getenv("CORS_ALLOW_ORIGINS", "*").strip()
if CORS_ALLOW_ORIGINS == "*":
    ALLOW_ORIGINS = ["*"]
else:
    ALLOW_ORIGINS = [o.strip() for o in CORS_ALLOW_ORIGINS.split(",") if o.strip()]

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "3"))
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.3"))
MAX_HISTORY_TURNS = int(os.getenv("CHAT_HISTORY_TURNS", "8"))
MAX_HISTORY_CHARS = int(os.getenv("MAX_HISTORY_CHARS", "1600"))
MAX_DOC_CONTEXT_CHARS = int(os.getenv("MAX_DOC_CONTEXT_CHARS", "2400"))
MAX_REQUESTS_PER_MINUTE = int(os.getenv("MAX_REQUESTS_PER_MINUTE", "60"))
MAX_ANSWER_CHARS_STREAM_CHUNK = int(os.getenv("STREAM_CHUNK_SIZE", "80"))

INDEX_PATH = BASE_DIR / "data" / "traffic_law_index.json"
INTENT_MODEL_PATH = BASE_DIR / "data" / "intent_model.joblib"
FEEDBACK_PATH = BASE_DIR / "data" / "feedback.jsonl"

try:
    import joblib
except Exception:
    joblib = None

try:
    with INDEX_PATH.open(encoding="utf-8") as f:
        INDEX: List[Dict[str, Any]] = json.load(f)
except FileNotFoundError:
    print(f"[WARNING] INDEX file tidak ditemukan: {INDEX_PATH}. RAG akan jalan tanpa konteks.")
    INDEX = []
except Exception as e:
    print(f"[WARNING] Gagal membaca index: {e}")
    INDEX = []

INTENT_MODEL = None
if joblib is not None:
    try:
        INTENT_MODEL = joblib.load(INTENT_MODEL_PATH)
    except Exception as e:
        print(f"[WARNING] Gagal memuat intent model: {e}")
        INTENT_MODEL = None

SMART_DISCLAIMER_ID = (
    "Catatan singkat: jawaban ini bersifat informasi umum dan edukasi keselamatan; "
    "untuk kasus spesifik, cek rambu/lokasi setempat dan pertimbangkan konfirmasi ke petugas/instansi terkait."
)
SMART_DISCLAIMER_EN = (
    "Quick note: this is general information for safety/education; for specific cases, check local signs/rules and consider confirming with authorities."
)

FAQ_RULES = [
    {
        "category": "SIM",
        "patterns": [r"\bsim\b", r"buat sim", r"perpanjang sim", r"sim mati", r"sim habis", r"sim hilang"],
        "answer_id": (
            "Kalau soal SIM, biasanya ada 3 skenario: bikin baru, perpanjang, atau hilang/rusak.\n"
            "- Bikin baru: siapkan identitas (KTP), cek syarat usia, ikut ujian teori & praktik sesuai jenis SIM.\n"
            "- Perpanjang: usahakan sebelum masa berlaku habis; siapkan KTP, SIM lama, dan ikuti prosedur perpanjangan.\n"
            "- Hilang/rusak: umumnya perlu surat keterangan/laporan sesuai ketentuan layanan, lalu proses penggantian.\n"
            "Intinya: tentukan dulu kamu mau bikin baru/perpanjang/hilang, nanti aku bisa arahkan langkah yang pas."
        ),
        "answer_en": (
            "For a driving license, it’s usually one of these: new, renewal, or lost/damaged.\n"
            "- New: prepare ID, meet age requirements, pass theory & practical tests.\n"
            "- Renewal: renew before expiry; bring required documents.\n"
            "- Lost/damaged: you may need a report/statement, then apply for replacement.\n"
            "Bottom line: tell me which case you have, and I’ll guide the right steps."
        ),
    },
    {
        "category": "STNK",
        "patterns": [r"\bstnk\b", r"pajak", r"stnk mati", r"stnk habis", r"perpanjang stnk"],
        "answer_id": (
            "Untuk STNK/pajak kendaraan, biasanya yang perlu kamu pastikan: masa berlaku, status pajak tahunan, dan kalau ada pengesahan.\n"
            "Kalau kamu jelasin: jenis kendaraan (motor/mobil) dan statusnya (pajak tahunan/5 tahunan), aku bisa bantu langkah-langkahnya.\n"
            "Intinya: sebutkan motor/mobil + pajak tahunan atau 5 tahunan, biar jawabanku tepat."
        ),
        "answer_en": (
            "For vehicle registration/tax, the key is the validity period and whether it’s annual vs the bigger periodic renewal.\n"
            "Tell me: motorcycle/car + annual tax or the periodic renewal, and I’ll guide the steps.\n"
            "Bottom line: share vehicle type and renewal type so I can be precise."
        ),
    },
    {
        "category": "Helm & Safety",
        "patterns": [r"helm", r"tidak pakai helm", r"sabuk pengaman", r"seatbelt", r"pengaman"],
        "answer_id": (
            "Soal keselamatan: helm standar + dipakai dengan benar itu penting banget, begitu juga sabuk pengaman.\n"
            "Selain urusan aturan, dampak utamanya soal mengurangi risiko cedera kepala/cedera fatal saat kecelakaan.\n"
            "Intinya: pakai perlindungan yang benar itu bukan cuma biar aman dari tilang, tapi buat nyelametin nyawa."
        ),
        "answer_en": (
            "Safety-wise: a proper helmet and seatbelt reduce the risk of severe injury.\n"
            "It’s not only about rules—this is about preventing head trauma and fatal injuries.\n"
            "Bottom line: use correct protection primarily to stay alive, not just to avoid tickets."
        ),
    },
    {
        "category": "Lampu merah & rambu",
        "patterns": [r"lampu merah", r"rambu", r"melanggar rambu", r"stop line", r"marka"],
        "answer_id": (
            "Kalau soal lampu merah/rambu: prinsipnya ikut sinyal & marka, dan berhenti di garis henti bila ada.\n"
            "Kalau kamu sebutkan lokasinya (persimpangan besar/kecil) dan situasinya (ramai/sepi, ada kamera ETLE atau nggak), aku bisa bantu analisisnya lebih pas.\n"
            "Intinya: jelasin konteks lokasi & kondisi biar aku bisa jawab lebih tepat."
        ),
        "answer_en": (
            "For red lights/signs: follow signals and road markings, and stop at the stop line if present.\n"
            "If you tell me the intersection type and whether there’s ETLE camera, I can be more precise.\n"
            "Bottom line: share context so I can answer accurately."
        ),
    },
    {
        "category": "ETLE/Tilang",
        "patterns": [r"\betle\b", r"tilang", r"surat tilang", r"kena kamera", r"e-tilang"],
        "answer_id": (
            "Kalau ETLE/tilang: biasanya yang penting itu jenis pelanggaran, bukti (foto/video), dan langkah tindak lanjut (konfirmasi/penyelesaian).\n"
            "Biar aku bantu tepat: itu tilang ETLE atau manual, dan kendaraannya motor atau mobil?\n"
            "Intinya: sebutkan ETLE/manual + motor/mobil, nanti aku arahkan langkah aman dan tertibnya."
        ),
        "answer_en": (
            "For tickets/ETLE: key points are violation type, evidence (photo/video), and follow-up steps.\n"
            "Tell me: ETLE or manual, and motorcycle or car.\n"
            "Bottom line: share ETLE/manual + vehicle type and I’ll guide you properly."
        ),
    },
]

class TTLCache:
    def __init__(self, ttl_seconds: int, max_items: int):
        self.ttl = ttl_seconds
        self.max_items = max_items
        self.data: Dict[str, Tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        now = time.time()
        item = self.data.get(key)
        if not item:
            return None
        exp, val = item
        if exp < now:
            self.data.pop(key, None)
            return None
        return val

    def set(self, key: str, val: Any):
        now = time.time()
        if len(self.data) >= self.max_items:
            oldest_key = None
            oldest_exp = None
            for k, (exp, _) in self.data.items():
                if oldest_exp is None or exp < oldest_exp:
                    oldest_exp = exp
                    oldest_key = k
            if oldest_key is not None:
                self.data.pop(oldest_key, None)
        self.data[key] = (now + self.ttl, val)

EMBED_CACHE = TTLCache(3600, 3000)
DOCS_CACHE = TTLCache(900, 3000)
PREF_CACHE = TTLCache(3600, 5000)

RATE_STATE: Dict[str, Tuple[float, int]] = {}

app = FastAPI(
    title="Hukum Lalu Lintas Chatbot (RAG + Gemini)",
    description="Backend chatbot hukum lalu lintas dengan RAG manual dan Gemini",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_credentials=False if ALLOW_ORIGINS == ["*"] else True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.on_event("startup")
def on_startup():
    init_db()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)

def _norm(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s

def _sha(s: str) -> str:
    return hashlib.sha256((s or "").encode("utf-8")).hexdigest()

def _client_ip(req: Request) -> str:
    xf = req.headers.get("x-forwarded-for") or ""
    if xf:
        return xf.split(",")[0].strip()
    xr = req.headers.get("x-real-ip") or ""
    if xr:
        return xr.strip()
    return (req.client.host if req.client else "unknown")

def _rate_limit_ok(ip: str) -> bool:
    now = time.time()
    start, count = RATE_STATE.get(ip, (now, 0))
    if now - start >= 60:
        RATE_STATE[ip] = (now, 1)
        return True
    if count >= MAX_REQUESTS_PER_MINUTE:
        RATE_STATE[ip] = (start, count)
        return False
    RATE_STATE[ip] = (start, count + 1)
    return True

def detect_language(text: str) -> str:
    t = _norm(text)
    if not t:
        return "id"
    en_hits = 0
    id_hits = 0
    en_words = {"hello", "hi", "thanks", "please", "car", "motorcycle", "traffic", "ticket", "license", "accident", "road"}
    id_words = {"halo", "hai", "makasih", "terima", "tolong", "motor", "mobil", "lalu", "lintas", "tilang", "sim", "kecelakaan", "jalan"}
    for w in t.split():
        if w in en_words:
            en_hits += 1
        if w in id_words:
            id_hits += 1
    return "en" if en_hits > id_hits else "id"

def looks_like_prompt_injection(q: str) -> bool:
    t = _norm(q)
    bad = [
        "ignore previous", "ignore all", "abaikan instruksi", "abaikan semua",
        "system prompt", "developer message", "bocorkan", "api key", "kunci api",
        "password", "token rahasia", "jailbreak", "bypass"
    ]
    return any(b in t for b in bad)

def safety_refuse_or_redirect(q: str, lang: str) -> Optional[str]:
    t = _norm(q)
    illegal = [
        "cara kabur dari polisi", "cara menghindari tilang", "cara lolos etle",
        "plat palsu", "nomor polisi palsu", "hapus bukti", "manipulasi etle", "nembus razia"
    ]
    if any(x in t for x in illegal):
        if lang == "en":
            return (
                "I can’t help with evading law enforcement or bypassing traffic enforcement. "
                "If you want, tell me the situation and I can suggest legal, safe options.\n"
                "Bottom line: I can help you stay safe and compliant, not evade enforcement."
            )
        return (
            "Aku nggak bisa bantu cara menghindari penegakan hukum/tilang atau trik lolos razia. "
            "Kalau kamu ceritain situasinya, aku bisa bantu opsi yang legal dan aman.\n"
            "Intinya: aku bantu yang aman dan sesuai aturan, bukan cara mengelabui."
        )
    return None

def is_traffic_related(question: str) -> bool:
    q = _norm(question)
    keywords = [
        "lalu lintas","angkutan jalan","jalan raya","jalan tol","helm","sabuk pengaman",
        "motor","mobil","kendaraan","sim","stnk","tilang","etle","ngebut","batas kecepatan",
        "rambu","marka","stop line","zebra cross","penyeberangan",
        "lampu merah","lampu kuning","lampu hijau","lampu lalu lintas","traffic light","apill",
        "polisi lalu lintas","pengemudi","penumpang","berkendara",
        "parkir","kecelakaan","tabrakan","menabrak","putar balik","melawan arus","menyalip","bahu jalan"
    ]
    if any(k in q for k in keywords):
        return True
    if re.search(r"\blampu\b.*\b(kuning|merah|hijau)\b", q):
        return True
    return False

def smalltalk_match(question: str) -> Optional[str]:
    q = _norm(question)
    if not q:
        return None
    greetings = [
        "hai","halo","hi","hello","pagi","siang","sore","malam","assalamualaikum",
        "permisi","tes","test","cek","coba","yow","yo"
    ]
    thanks = ["makasih","terima kasih","thanks","thx","mantap","sip","oke","ok","nice","keren"]
    if q in greetings or any(q.startswith(g + " ") for g in greetings):
        return "greet"
    if q in thanks or any(t in q for t in thanks):
        return "thanks"
    if q in ("wkwk","haha","hehe","lol"):
        return "laugh"
    return None

def smalltalk_answer(kind: str, lang: str) -> str:
    if lang == "en":
        if kind == "thanks":
            return "You’re welcome. What traffic/safety topic do you want to ask about?\nBottom line: ask me anything about traffic rules or safe driving."
        if kind == "laugh":
            return "😄 Got it. Want to ask about traffic rules, tickets, or safe driving?\nBottom line: tell me what you’re curious about."
        return "Hi. Tell me your question about traffic rules or a driving situation.\nBottom line: share the situation and I’ll help."
    if kind == "thanks":
        return "Sama-sama ya. Mau tanya topik apa soal lalu lintas?\nIntinya: sebutin situasinya, aku bantu."
    if kind == "laugh":
        return "😄 Oke. Mau tanya soal aturan, tilang/ETLE, atau tips aman?\nIntinya: bilang aja situasinya."
    return "Hai. Kamu mau tanya soal aturan lalu lintas atau kejadian apa?\nIntinya: ceritain singkat situasinya, biar aku bantu."

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = 0.0
    n1 = 0.0
    n2 = 0.0
    for a, b in zip(v1, v2):
        dot += a * b
        n1 += a * a
        n2 += b * b
    if n1 == 0.0 or n2 == 0.0:
        return 0.0
    return dot / (math.sqrt(n1) * math.sqrt(n2))

def embed_text(text: str) -> List[float]:
    if not GEMINI_ENABLED or CLIENT is None:
        raise RuntimeError("Gemini tidak aktif")
    t = (text or "").strip()
    if not t:
        return []
    key = "emb:" + _sha(t)
    cached = EMBED_CACHE.get(key)
    if cached is not None:
        return cached
    result = CLIENT.models.embed_content(model=EMBED_MODEL, contents=t)
    vec = result.embeddings[0].values
    EMBED_CACHE.set(key, vec)
    return vec

def search_top_k(query_embedding: List[float], k: int, min_score: float) -> List[Dict[str, Any]]:
    if not INDEX or not query_embedding:
        return []
    key = "docs:" + _sha(json.dumps(query_embedding[:32], ensure_ascii=False))
    cached = DOCS_CACHE.get(key)
    if cached is not None:
        return cached
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for doc in INDEX:
        emb = doc.get("embedding") or []
        s = cosine_similarity(query_embedding, emb)
        scored.append((s, doc))
    scored.sort(key=lambda x: x[0], reverse=True)
    out: List[Dict[str, Any]] = []
    for s, d in scored[:max(k, 1)]:
        if s >= min_score:
            dd = dict(d)
            dd["score"] = float(s)
            out.append(dd)
    DOCS_CACHE.set(key, out)
    return out

def predict_intent(question: str) -> str:
    q = _norm(question)
    hukum_keywords = ["pasal","undang-undang","uu ","uu no","uu nomor","denda","sanksi","pidana","ayat","tilang","etle"]
    if any(k in q for k in hukum_keywords):
        return "butuh_pasal"
    if INTENT_MODEL is None:
        return "tips_umum"
    try:
        return str(INTENT_MODEL.predict([question])[0])
    except Exception:
        return "tips_umum"

def detect_tone(question: str) -> str:
    q = _norm(question)
    slang = ["ga","gak","gk","nggak","ngga","wkwk","haha","hehe","kok","aja"]
    if any(s in q for s in slang):
        return "santai"
    return "formal"

def parse_pref_patch(question: str) -> Dict[str, Any]:
    q = _norm(question)
    patch: Dict[str, Any] = {}

    if ("jawab singkat" in q) or ("jawaban singkat" in q) or ("singkat aja" in q) or ("singkatnya" in q) or ("ringkas" in q) or ("pendek" in q):
        patch["verbosity"] = "short"
    if ("jawab panjang" in q) or ("jawaban panjang" in q) or ("jawaban detail" in q) or ("detail" in q) or ("jelasin lengkap" in q) or ("lengkap" in q):
        patch["verbosity"] = "long"

    if "santai aja" in q or "bahasa santai" in q:
        patch["tone_pref"] = "santai"
    if "formal aja" in q or "bahasa formal" in q:
        patch["tone_pref"] = "formal"

    return patch

def _is_preference_only(question: str, patch: Dict[str, Any]) -> bool:
    if not patch:
        return False
    if is_traffic_related(question):
        return False
    if smalltalk_match(question) is not None:
        return False

    q = _norm(question)
    cleaned = re.sub(r"[^\w\s]", " ", q)
    cleaned = re.sub(
        r"\b(aku|saya|mau|ingin|tolong|pls|please|dong|ya|yah|deh|jawab|jawaban|singkat|ringkas|pendek|detail|panjang|lengkap|aja|saja|kok|nih|gimana|bagaimana)\b",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return len(cleaned.split()) <= 2

def get_session_prefs(db: Session, session_id: int) -> Dict[str, Any]:
    ck = f"pref:{session_id}"
    cached = PREF_CACHE.get(ck)
    if isinstance(cached, dict):
        return cached
    key = f"session_pref:{session_id}"
    try:
        meta = db.query(SystemMeta).filter(SystemMeta.key == key).first()
    except Exception:
        meta = None
    if not meta or not getattr(meta, "value", None):
        PREF_CACHE.set(ck, {})
        return {}
    try:
        data = json.loads(meta.value)
        if isinstance(data, dict):
            PREF_CACHE.set(ck, data)
            return data
    except Exception:
        pass
    PREF_CACHE.set(ck, {})
    return {}

def set_session_prefs(db: Session, session_id: int, patch: Dict[str, Any]) -> Dict[str, Any]:
    if not patch:
        return get_session_prefs(db, session_id)
    cur = get_session_prefs(db, session_id)
    merged = dict(cur)
    merged.update(patch)
    key = f"session_pref:{session_id}"
    try:
        meta = db.query(SystemMeta).filter(SystemMeta.key == key).first()
        if meta is None:
            meta = SystemMeta(key=key, value=json.dumps(merged, ensure_ascii=False))
            db.add(meta)
        else:
            meta.value = json.dumps(merged, ensure_ascii=False)
        db.commit()
    except Exception:
        db.rollback()
    PREF_CACHE.set(f"pref:{session_id}", merged)
    return merged

def compute_verbosity(question: str, intent: str, prefs: Dict[str, Any]) -> str:
    if prefs.get("verbosity") in ("short","normal","long"):
        return prefs["verbosity"]
    q = _norm(question)
    if "singkat" in q or "ringkas" in q or "pendek" in q:
        return "short"
    if "detail" in q or "lengkap" in q or "panjang" in q:
        return "long"
    if intent == "butuh_pasal":
        return "normal"
    if len(q.split()) <= 6:
        return "short"
    return "normal"

def postprocess_answer_by_verbosity(text: str, verbosity: str) -> str:
    t = (text or "").strip()
    if not t:
        return t
    if verbosity != "short":
        return t

    sentences = re.split(r"(?<=[\.\?\!])\s+", t)
    sentences = [s.strip() for s in sentences if s.strip()]
    head = " ".join(sentences[:2]).strip() if sentences else t

    summary = None
    for line in reversed(t.splitlines()):
        line = line.strip()
        if line.lower().startswith("intinya"):
            summary = line
            break

    if summary and summary not in head:
        return (head + "\n\n" + summary).strip()

    return head.strip()

def _shorten(s: str, n: int) -> str:
    s = (s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n]
    sp = cut.rfind(" ")
    if sp > 80:
        cut = cut[:sp]
    return cut.rstrip() + "..."

def fetch_history_text(db: Session, session_id: int) -> str:
    try:
        msgs = (
            db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.desc())
            .limit(MAX_HISTORY_TURNS)
            .all()
        )
    except Exception:
        return ""
    if not msgs:
        return ""
    msgs = list(reversed(msgs))
    parts: List[str] = []
    for m in msgs:
        role = (m.role or "").strip().lower()
        txt = (m.content or "").strip()
        if not txt:
            continue
        tag = "User" if role == "user" else "Asisten"
        parts.append(f"{tag}: {_shorten(txt, 260)}")
    return _shorten("\n".join(parts).strip(), MAX_HISTORY_CHARS)

def action_helper_mode(question: str) -> bool:
    q = _norm(question)
    triggers = ["apa yang harus saya lakukan","apa yg harus saya lakukan","langkah","step","cara","tahapan","prosedur","gimana urutannya"]
    return any(t in q for t in triggers)

def case_intake_questions(question: str) -> List[str]:
    q = _norm(question)
    qs: List[str] = []
    if len(q.split()) <= 3 and smalltalk_match(q) is None:
        qs.append("Maksudnya kamu nanya soal apa persisnya, dan situasinya gimana?")
    if "tilang" in q or "etle" in q:
        if "etle" not in q and "manual" not in q:
            qs.append("Itu tilang manual atau ETLE?")
        if "motor" not in q and "mobil" not in q:
            qs.append("Kendaraannya motor atau mobil?")
    if "kecelakaan" in q or "tabrakan" in q or "menabrak" in q:
        if "korban" not in q and "luka" not in q and "meninggal" not in q:
            qs.append("Ada korban luka atau hanya kerusakan kendaraan?")
        if "tol" not in q and "jalan" in q:
            qs.append("Kejadiannya di jalan kota atau tol?")
    if "parkir" in q:
        if "rambu" not in q and "bahu" not in q:
            qs.append("Parkirnya di bahu jalan atau area parkir resmi, dan ada rambu larangan parkir nggak?")
    out: List[str] = []
    seen = set()
    for x in qs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out[:3]

def clarify_message(tone: str, lang: str, qs: List[str]) -> str:
    if lang == "en":
        if qs:
            lines = ["To answer accurately, I need a bit more context:"]
            lines += [f"- {x}" for x in qs]
            lines.append("Bottom line: reply with those details and I’ll help.")
            return "\n".join(lines)
        return "Could you share a bit more context so I can answer precisely?\nBottom line: add details and I’ll help."
    if qs:
        intro = "Biar aku jawab tepat, aku tanya sedikit ya:" if tone == "santai" else "Agar jawabannya tepat, saya perlu memastikan beberapa hal:"
        lines = [intro] + [f"- {x}" for x in qs] + ["Intinya: jawab poin di atas, nanti aku bantu jawab paling pas."]
        return "\n".join(lines)
    return "Boleh jelasin sedikit konteksnya? Biar aku jawab lebih pas.\nIntinya: tambah detail, nanti aku bantu."

def faq_match(question: str) -> Optional[Dict[str, Any]]:
    q = _norm(question)
    for rule in FAQ_RULES:
        for pat in rule["patterns"]:
            if re.search(pat, q):
                return rule
    return None

def suggested_next_questions(intent: str, question: str) -> List[str]:
    q = _norm(question)
    out: List[str] = []
    if "tilang" in q or "etle" in q:
        out += ["Itu ETLE atau tilang manual?", "Pelanggarannya apa persisnya?", "Mau langkah-langkah penyelesaiannya?"]
    if "parkir" in q:
        out += ["Lokasinya ada rambu larangan parkir?", "Parkirnya di bahu jalan atau area parkir resmi?", "Mau tips parkir aman?"]
    if "kecelakaan" in q or "tabrakan" in q:
        out += ["Ada korban luka atau hanya kerusakan?", "Butuh langkah-langkah setelah kecelakaan?", "Mau susun kronologi singkat?"]
    if smalltalk_match(q) is not None:
        out += ["Tanya soal ETLE/tilang", "Tanya soal SIM/STNK", "Tanya soal aturan helm & keselamatan"]
    if intent == "butuh_pasal":
        out += ["Mau versi ringkas pasal terkait?", "Mau jelasin keselamatan di balik aturannya?", "Kejadiannya motor atau mobil?"]
    if not out:
        out = ["Motor atau mobil?", "Kejadiannya di mana?", "Mau jawaban singkat atau detail?"]
    dedup: List[str] = []
    seen = set()
    for x in out:
        if x and x not in seen:
            seen.add(x)
            dedup.append(x)
    return dedup[:3]

def build_context(docs: List[Dict[str, Any]], history: str, meta: Dict[str, Any]) -> str:
    parts: List[str] = []

    if meta:
        lines: List[str] = []
        lines.append("BAHASA_JAWABAN: English" if meta.get("language") == "en" else "BAHASA_JAWABAN: Indonesia")
        if meta.get("verbosity"):
            lines.append(f"PANJANG_JAWABAN: {meta['verbosity']}")
        if meta.get("mode"):
            lines.append(f"MODE: {meta['mode']}")
        lines.append("SAFETY: jangan mengarang pasal/UU; jika ragu, minta klarifikasi; fokus keselamatan dan kepatuhan.")
        lines.append("KONSISTENSI: jawab terstruktur, jelas, tidak menggurui, dan akhiri 1 kalimat ringkasan inti.")
        if meta.get("mode") == "action_helper":
            lines.append("FORMAT: jika memberi langkah, gunakan langkah bernomor (1), (2), (3) dan opsi alternatif bila perlu.")
        parts.append("ATURAN TAMBAHAN:\n" + "\n".join(lines))

    if history:
        parts.append("RIWAYAT PERCAKAPAN:\n" + history)

    if not docs:
        parts.append("KONTEKS DOKUMEN:\nTidak ada konteks dokumen yang relevan ditemukan.")
        return "\n\n".join(parts).strip()

    doc_blocks: List[str] = []
    total = 0
    for i, d in enumerate(docs, start=1):
        judul = (d.get("judul") or f"Dokumen {i}").strip()
        isi = (d.get("isi") or "").strip()
        block = f"[{i}] {judul}\n{isi}".strip()
        block = _shorten(block, 1400)
        if total + len(block) > MAX_DOC_CONTEXT_CHARS:
            break
        doc_blocks.append(block)
        total += len(block)

    parts.append("KONTEKS DOKUMEN:\n" + ("\n\n".join(doc_blocks) if doc_blocks else "Tidak ada konteks dokumen yang relevan ditemukan."))
    return "\n\n".join(parts).strip()

def _is_quota_error(e: Exception) -> bool:
    s = str(e).lower()
    return ("resource_exhausted" in s) or ("429" in s) or ("quota" in s) or ("rate" in s)

def _is_not_found_model_error(e: Exception) -> bool:
    s = str(e).lower()
    return ("not_found" in s) or ("is not found" in s) or ("call listmodels" in s)

def _model_candidates(model: str) -> List[str]:
    m = (model or "").strip()
    if not m:
        return []
    out = [m]
    if not m.endswith("-latest"):
        out.append(m + "-latest")
    return out

def generate_answer(question: str, context: str, tone: str = "formal") -> Tuple[str, str]:
    if not GEMINI_ENABLED or CLIENT is None:
        raise RuntimeError("Gemini tidak aktif")

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

    last_err: Optional[Exception] = None
    for base_model in GEN_MODELS:
        for model in _model_candidates(base_model):
            try:
                res = CLIENT.models.generate_content(model=model, contents=prompt)
                text = (res.text or "").strip()
                if text:
                    return text, model
            except Exception as e:
                last_err = e
                if _is_not_found_model_error(e):
                    continue
                if _is_quota_error(e):
                    continue
                break
    raise last_err or RuntimeError("Gemini tidak mengembalikan jawaban")

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
    intent: str | None = None
    tone: str | None = None
    mode: str | None = None
    category: str | None = None
    suggested_questions: List[str] = []
    model_used: str | None = None
    disclaimer: str | None = None

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
        last_msg = max(messages, key=lambda m: m.created_at or datetime.min.replace(tzinfo=timezone.utc))
    preview = None
    if last_msg:
        text = (last_msg.content or "").strip()
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
    return ChatMessageOut(id=msg.id, role=msg.role, content=msg.content, created_at=msg.created_at)

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
        try:
            vec = embed_text(isi)
        except Exception:
            vec = []
        if not vec:
            continue
        new_index.append({"id": doc_id, "judul": judul, "isi": isi, "embedding": vec})
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        json.dump(new_index, f, ensure_ascii=False, indent=2)
    global INDEX
    INDEX = new_index
    return len(new_index)

@app.get("/")
async def root():
    return {"status": "ok", "message": "Backend hukum lalu lintas siap."}

def ensure_session(db: Session, username: Optional[str], session_id: Optional[int], title_seed: str) -> ChatSession:
    username_raw = (username or "").strip()
    if session_id:
        s = db.get(ChatSession, session_id)
        if s is not None:
            return s
    if username_raw:
        s = ChatSession(username=username_raw, title=(title_seed or "")[:120])
    else:
        guest_name = "guest:" + secrets.token_urlsafe(8)
        s = ChatSession(username=guest_name, title=(title_seed or "Konsultasi")[:120])
    db.add(s)
    db.commit()
    db.refresh(s)
    return s

def build_sources(intent: str, query_emb: List[float], docs: List[Dict[str, Any]]) -> List[SourceDoc]:
    if intent != "butuh_pasal" or not query_emb or not docs:
        return []
    out: List[SourceDoc] = []
    for d in docs:
        sc = float(d.get("score") or cosine_similarity(query_emb, d.get("embedding") or []))
        out.append(SourceDoc(id=str(d.get("id","")), judul=d.get("judul",""), isi=d.get("isi",""), score=sc))
    return out

def final_disclaimer(lang: str) -> str:
    return SMART_DISCLAIMER_EN if lang == "en" else SMART_DISCLAIMER_ID

def should_append_disclaimer(intent: str, answer: str) -> bool:
    if not answer:
        return True
    if intent == "butuh_pasal":
        return True
    return False

async def _chat_impl(req: ChatRequest, request: Request, db: Session) -> ChatResponse:
    ip = _client_ip(request)
    if not _rate_limit_ok(ip):
        raise HTTPException(status_code=429, detail="Terlalu banyak request. Coba lagi sebentar.")

    question = (req.question or "").strip()
    if not question:
        return ChatResponse(
            answer="Silakan ajukan pertanyaan seputar lalu lintas atau hukum lalu lintas.",
            sources=[],
            session_id=req.session_id,
            suggested_questions=["Tanya soal ETLE/tilang", "Tanya soal SIM/STNK", "Tanya soal aturan helm & keselamatan"],
            disclaimer=final_disclaimer("id"),
        )

    lang = detect_language(question)

    inj = looks_like_prompt_injection(question)
    if inj:
        ans = (
            "Aku nggak bisa mengikuti instruksi yang mencoba mengabaikan aturan/sistem atau meminta hal rahasia. "
            "Kalau kamu tanya soal lalu lintas, aku bantu dengan aman dan sesuai aturan.\n"
            "Intinya: jelasin pertanyaan lalu lintasnya, aku jawab."
        ) if lang != "en" else (
            "I can’t follow requests to bypass system rules or reveal secrets. "
            "If you ask about traffic rules/safety, I’ll help safely.\n"
            "Bottom line: ask a traffic question and I’ll answer."
        )
        return ChatResponse(
            answer=ans,
            sources=[],
            session_id=req.session_id,
            mode="safety",
            intent="tips_umum",
            tone="formal",
            suggested_questions=suggested_next_questions("tips_umum", question),
            disclaimer=final_disclaimer(lang),
        )

    safety_block = safety_refuse_or_redirect(question, lang)
    if safety_block:
        return ChatResponse(
            answer=safety_block,
            sources=[],
            session_id=req.session_id,
            mode="safety",
            intent="tips_umum",
            tone="formal",
            suggested_questions=suggested_next_questions("tips_umum", question),
            disclaimer=final_disclaimer(lang),
        )

    sk = smalltalk_match(question)
    if sk is not None:
        tone = detect_tone(question)
        s = ensure_session(db, req.username, req.session_id, title_seed=question)
        prefs = get_session_prefs(db, s.id)
        patch = parse_pref_patch(question)
        if patch:
            prefs = set_session_prefs(db, s.id, patch)
        if prefs.get("tone_pref") in ("santai","formal"):
            tone = prefs["tone_pref"]

        ans = smalltalk_answer(sk, lang)

        db.add(ChatMessage(session_id=s.id, role="user", content=question))
        db.add(ChatMessage(session_id=s.id, role="assistant", content=ans))
        s.updated_at = _now_utc()
        db.commit()

        return ChatResponse(
            answer=ans,
            sources=[],
            session_id=s.id,
            intent="smalltalk",
            tone=tone,
            mode="smalltalk",
            suggested_questions=suggested_next_questions("smalltalk", question),
            disclaimer=final_disclaimer(lang),
        )

    s = ensure_session(db, req.username, req.session_id, title_seed=question)
    prefs = get_session_prefs(db, s.id)

    patch = parse_pref_patch(question)
    if patch:
        prefs = set_session_prefs(db, s.id, patch)

    if _is_preference_only(question, patch):
        tone = detect_tone(question)
        if prefs.get("tone_pref") in ("santai","formal"):
            tone = prefs["tone_pref"]
        vb = prefs.get("verbosity", "normal")
        if vb == "short":
            ans = (
                "Siap. Untuk sesi ini aku jawab singkat ya. Sekarang kamu mau tanya apa soal lalu lintas? 🙂\n"
                "Intinya: tulis pertanyaan lalu lintasnya, nanti aku jawab ringkas."
            ) if lang != "en" else (
                "Got it. I’ll keep answers short for this session. What traffic question do you have? 🙂\n"
                "Bottom line: ask a traffic question and I’ll answer briefly."
            )
        elif vb == "long":
            ans = (
                "Siap. Untuk sesi ini aku jawab lebih detail ya. Sekarang kamu mau tanya apa soal lalu lintas? 🙂\n"
                "Intinya: tulis pertanyaan lalu lintasnya, nanti aku jelasin lengkap."
            ) if lang != "en" else (
                "Got it. I’ll answer in more detail for this session. What traffic question do you have? 🙂\n"
                "Bottom line: ask a traffic question and I’ll answer thoroughly."
            )
        else:
            ans = (
                "Oke. Preferensi jawaban sudah aku simpan untuk sesi ini. Sekarang kamu mau tanya apa soal lalu lintas? 🙂\n"
                "Intinya: tulis pertanyaan lalu lintasnya, nanti aku bantu."
            ) if lang != "en" else (
                "Okay. I saved your preference for this session. What traffic question do you have? 🙂\n"
                "Bottom line: ask a traffic question and I’ll help."
            )

        db.add(ChatMessage(session_id=s.id, role="user", content=question))
        db.add(ChatMessage(session_id=s.id, role="assistant", content=ans))
        s.updated_at = _now_utc()
        db.commit()

        return ChatResponse(
            answer=ans,
            sources=[],
            session_id=s.id,
            intent="meta",
            tone=tone,
            mode="preference_set",
            category="preferences",
            suggested_questions=suggested_next_questions("meta", question),
            disclaimer=final_disclaimer(lang),
        )

    intent = predict_intent(question)
    tone = detect_tone(question)
    if prefs.get("tone_pref") in ("santai","formal"):
        tone = prefs["tone_pref"]

    verbosity = compute_verbosity(question, intent, prefs)
    mode = "answer"
    category = None

    faq = faq_match(question)
    if faq is not None and intent != "butuh_pasal" and is_traffic_related(question):
        mode = "faq"
        category = faq.get("category")
        ans = faq["answer_en"] if lang == "en" else faq["answer_id"]
        disc = final_disclaimer(lang)
        if disc and should_append_disclaimer(intent, ans):
            ans = ans.strip() + "\n\n" + disc

        db.add(ChatMessage(session_id=s.id, role="user", content=question))
        db.add(ChatMessage(session_id=s.id, role="assistant", content=ans))
        s.updated_at = _now_utc()
        db.commit()

        return ChatResponse(
            answer=ans,
            sources=[],
            session_id=s.id,
            intent=intent,
            tone=tone,
            mode=mode,
            category=category,
            suggested_questions=suggested_next_questions(intent, question),
            disclaimer=disc,
        )

    if not is_traffic_related(question):
        ans = (
            "Maaf, aku fokus membantu pertanyaan yang masih berkaitan dengan lalu lintas dan hukum lalu lintas di Indonesia. "
            "Kalau kamu mau, coba tulis ulang pertanyaannya supaya tetap tentang aturan jalan, keselamatan, SIM/STNK, rambu, ETLE, atau kejadian di jalan.\n"
            "Intinya: ubah pertanyaan ke topik lalu lintas, nanti aku bantu."
        ) if lang != "en" else (
            "Sorry—I can only help with traffic rules/safety in Indonesia. "
            "Please rephrase your question to be about road rules, safety, license/registration, signs, ETLE, or a road incident.\n"
            "Bottom line: keep it traffic-related and I’ll help."
        )
        disc = final_disclaimer(lang)
        ans = ans.strip() + "\n\n" + disc

        db.add(ChatMessage(session_id=s.id, role="user", content=question))
        db.add(ChatMessage(session_id=s.id, role="assistant", content=ans))
        s.updated_at = _now_utc()
        db.commit()

        return ChatResponse(
            answer=ans,
            sources=[],
            session_id=s.id,
            intent=intent,
            tone=tone,
            mode="out_of_scope",
            suggested_questions=suggested_next_questions(intent, question),
            disclaimer=disc,
        )

    qs = case_intake_questions(question)
    if qs and (len(_norm(question).split()) <= 6 or intent == "butuh_pasal"):
        mode = "case_intake"
        ans = clarify_message(tone, lang, qs)
        disc = final_disclaimer(lang)
        ans = ans.strip() + "\n\n" + disc

        db.add(ChatMessage(session_id=s.id, role="user", content=question))
        db.add(ChatMessage(session_id=s.id, role="assistant", content=ans))
        s.updated_at = _now_utc()
        db.commit()

        return ChatResponse(
            answer=ans,
            sources=[],
            session_id=s.id,
            intent=intent,
            tone=tone,
            mode=mode,
            suggested_questions=suggested_next_questions(intent, question),
            disclaimer=disc,
        )

    history_text = fetch_history_text(db, s.id)

    query_emb: List[float] = []
    docs: List[Dict[str, Any]] = []
    try:
        query_emb = embed_text(question)
        docs = search_top_k(query_emb, k=RAG_TOP_K, min_score=RAG_MIN_SCORE)
    except Exception as e:
        print(f"[EMBED/RAG] failed: {e}")
        query_emb = []
        docs = []

    if intent == "butuh_pasal" and not docs:
        mode = "guardrail"
        ans = (
            "Aku bisa bantu, tapi aku belum punya konteks pasal/UU yang cukup dari dokumen yang tersedia. "
            "Biar nggak ngarang, boleh jelasin pelanggarannya apa, kendaraan apa, dan kejadian di mana (mis. jalan kota/tol, ada ETLE atau tidak)?\n"
            "Intinya: tambah detail dulu, nanti aku bantu cari dasar yang paling relevan."
        ) if lang != "en" else (
            "I can help, but I don’t have enough document context to cite a specific article/law without guessing. "
            "Tell me the exact violation, vehicle type, and where it happened (city road/toll, ETLE camera or not).\n"
            "Bottom line: share details and I’ll map it more accurately."
        )
        disc = final_disclaimer(lang)
        ans = ans.strip() + "\n\n" + disc

        db.add(ChatMessage(session_id=s.id, role="user", content=question))
        db.add(ChatMessage(session_id=s.id, role="assistant", content=ans))
        s.updated_at = _now_utc()
        db.commit()

        return ChatResponse(
            answer=ans,
            sources=[],
            session_id=s.id,
            intent=intent,
            tone=tone,
            mode=mode,
            suggested_questions=suggested_next_questions(intent, question),
            disclaimer=disc,
        )

    meta = {
        "language": lang,
        "verbosity": verbosity,
        "mode": "action_helper" if action_helper_mode(question) else "normal"
    }
    context_text = build_context(docs, history_text, meta)

    model_used = None
    try:
        answer_text, model_used = generate_answer(question, context_text, tone=tone)
    except Exception as e:
        print(f"[GEMINI] failed: {e}")
        if _is_quota_error(e):
            answer_text = (
                "Layanan AI sedang penuh atau kuota sedang habis. Coba lagi sebentar ya.\n"
                "Intinya: coba ulang beberapa saat lagi."
            ) if lang != "en" else (
                "The AI service is busy or quota is exhausted. Please try again shortly.\n"
                "Bottom line: retry in a moment."
            )
        else:
            answer_text = (
                "Ada kendala saat memproses jawaban AI. Coba ulang sebentar ya.\n"
                "Intinya: coba lagi beberapa saat."
            ) if lang != "en" else (
                "There was an issue generating the AI response. Please try again.\n"
                "Bottom line: retry shortly."
            )

    answer_text = postprocess_answer_by_verbosity(answer_text, verbosity)

    disc = final_disclaimer(lang)
    if disc and should_append_disclaimer(intent, answer_text):
        answer_text = answer_text.strip() + "\n\n" + disc

    sources = build_sources(intent, query_emb, docs)
    sugg = suggested_next_questions(intent, question)

    db.add(ChatMessage(session_id=s.id, role="user", content=question))
    db.add(ChatMessage(session_id=s.id, role="assistant", content=answer_text))
    s.updated_at = _now_utc()
    db.commit()

    return ChatResponse(
        answer=answer_text,
        sources=sources,
        session_id=s.id,
        intent=intent,
        tone=tone,
        mode=mode,
        category=category,
        suggested_questions=sugg,
        model_used=model_used,
        disclaimer=disc,
    )

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    return await _chat_impl(req, request, db)

@app.post("/chat-stream")
async def chat_stream(req: ChatRequest, request: Request):
    ip = _client_ip(request)
    if not _rate_limit_ok(ip):
        raise HTTPException(status_code=429, detail="Terlalu banyak request. Coba lagi sebentar.")

    async def _sleep_async(sec: float):
        import asyncio
        await asyncio.sleep(sec)

    async def event_gen():
        db = SessionLocal()
        try:
            yield "event: typing\ndata: 1\n\n"
            resp = await _chat_impl(req, request, db)
            text = resp.answer or ""
            i = 0
            while i < len(text):
                chunk = text[i : i + MAX_ANSWER_CHARS_STREAM_CHUNK]
                safe = chunk.replace("\n", "\\n")
                yield f"event: chunk\ndata: {safe}\n\n"
                i += MAX_ANSWER_CHARS_STREAM_CHUNK
                await _sleep_async(0.02)
            payload = {
                "session_id": resp.session_id,
                "intent": resp.intent,
                "tone": resp.tone,
                "mode": resp.mode,
                "category": resp.category,
                "suggested_questions": resp.suggested_questions,
                "sources": [s.model_dump() for s in (resp.sources or [])],
                "model_used": resp.model_used,
            }
            yield "event: done\ndata: " + json.dumps(payload, ensure_ascii=False).replace("\n"," ") + "\n\n"
        finally:
            try:
                db.close()
            except Exception:
                pass

    return StreamingResponse(event_gen(), media_type="text/event-stream")

@app.post("/feedback", response_model=SimpleMessageResponse)
def feedback(payload: Dict[str, Any], db: Session = Depends(get_db)):
    FEEDBACK_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = dict(payload)
    entry["created_at"] = _now_utc().isoformat()
    try:
        with FEEDBACK_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass
    return SimpleMessageResponse(message="Makasih, feedbacknya sudah diterima.")

@app.post("/auth/register", response_model=UserOut)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing_username = db.query(User).filter(User.username == payload.username).first()
    if existing_username:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username sudah dipakai. Silakan pilih username lain.")
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email sudah terdaftar.")
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
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Username/email atau password salah.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Akun tidak aktif.")
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
        expires_at = _now_utc() + timedelta(minutes=30)
        prt = PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at, used=False)
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
    now = _now_utc()
    if not token_obj or token_obj.expires_at < now:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token tidak valid atau sudah kadaluarsa.")
    user = db.query(User).filter(User.id == token_obj.user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User tidak ditemukan.")
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
        total = rebuild_index_from_db(db)
        now = _now_utc().isoformat()
        meta = db.query(SystemMeta).filter(SystemMeta.key == "rag_index_last_built_at").first()
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
        raise HTTPException(status_code=500, detail=f"Gagal membangun ulang index: {e}")

@app.get("/admin/index-status")
def admin_index_status(db: Session = Depends(get_db)):
    meta = db.query(SystemMeta).filter(SystemMeta.key == "rag_index_last_built_at").first()
    return {
        "last_built_at": meta.value if meta else None,
        "indexed_documents": len(INDEX),
        "embed_model": EMBED_MODEL,
        "gen_model": GEN_MODEL,
        "fallback_models": GEN_MODELS,
        "gemini_enabled": GEMINI_ENABLED,
    }

@app.get("/chat-history/{username}", response_model=List[ChatSessionSummary])
def get_chat_history(username: str, db: Session = Depends(get_db)):
    rows = db.query(ChatSession).filter(ChatSession.username == username).order_by(ChatSession.updated_at.desc()).all()
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
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)