import json
from typing import List, Any
from sqlalchemy import (Column, Integer, String, Text, DateTime,ForeignKey,Boolean,)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from db import Base

class LawArticle(Base):
    __tablename__ = "law_articles"

    id = Column(Integer, primary_key=True, index=True)
    uu = Column(String, nullable=False)
    pasal = Column(String, nullable=False)
    title = Column(String, nullable=True)
    legal_text = Column(Text, nullable=True)
    explanation = Column(Text, nullable=True)
    status = Column(String, nullable=False, default="berlaku")
    keywords_json = Column(Text, nullable=True)

    def get_keywords(self) -> List[str]:
        if not self.keywords_json:
            return []
        try:
            data: Any = json.loads(self.keywords_json)
            if isinstance(data, list):
                return [str(x) for x in data]
        except Exception:
            pass
        return []

    def set_keywords(self, keywords: List[str] | None) -> None:
        if not keywords:
            self.keywords_json = None
        else:
            self.keywords_json = json.dumps(list(keywords), ensure_ascii=False)

class SystemMeta(Base):
    __tablename__ = "system_meta"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    def __repr__(self) -> str:
        return f"<SystemMeta key={self.key!r} value={self.value!r}>"

class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), nullable=False, index=True)
    title = Column(String, nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    messages = relationship(
        "ChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ChatMessage.id",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(
        Integer,
        ForeignKey("chat_sessions.id"),
        nullable=False,
        index=True,
    )
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    session = relationship("ChatSession", back_populates="messages")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)

    username = Column(String(100), unique=True, nullable=False, index=True)

    email = Column(String(255), unique=True, nullable=False, index=True)
    full_name = Column(String(255), nullable=True)

    hashed_password = Column(String(255), nullable=False)

    is_active = Column(Boolean, nullable=False, default=True)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    reset_tokens = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    token = Column(String(100), unique=True, nullable=False, index=True)

    expires_at = Column(DateTime(timezone=True), nullable=False)

    used = Column(Boolean, nullable=False, default=False)

    created_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    user = relationship("User", back_populates="reset_tokens")
