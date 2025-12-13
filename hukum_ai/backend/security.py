from passlib.context import CryptContext

pwd_context = CryptContext(
    schemes=["pbkdf2_sha256"],
    deprecated="auto",
)

def hash_password(password: str) -> str:
    if not isinstance(password, str):
        raise TypeError("password harus string")

    if len(password) < 8:
        raise ValueError("Password terlalu pendek (minimal 8 karakter).")

    if len(password) > 256:
        password = password[:256]

    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if not plain_password or not hashed_password:
        return False

    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception:
        return False