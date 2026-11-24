import datetime
import uuid
from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import relationship
from app.db.session import Base

def generate_friend_code():
    return str(uuid.uuid4())[:8].upper()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    kakao_user_key = Column(String(128), unique=True, index=True, nullable=False)
    nickname = Column(String(64), default="대장장이")
    friend_code = Column(String(16), unique=True, index=True, default=generate_friend_code)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_login_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    active_run = relationship("Run", back_populates="user", uselist=False)
    ranking = relationship("Ranking", back_populates="user", uselist=False)

class Run(Base):
    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    round = Column(Integer, default=1)
    gold = Column(Integer, default=0)
    relic_points = Column(Integer, default=0)
    
    # JSON 컬럼
    # swords: [{"id": 1, "type": "normal", "level": 0}, ...]
    swords = Column(JSON, default=list)
    # items: ["protect_destroy", "revert_destroy", ...]
    items = Column(JSON, default=list)
    # relics: ["twin_rune", "merchants_tongue", ...]
    relics = Column(JSON, default=list)

    shield = Column(Integer, default=0) # 1회 방어 유물 활성화 여부
    boost = Column(Integer, default=0)  # 연속 유지 누적 보너스 스택
    destroyed_count = Column(Integer, default=0)
    status = Column(String(32), default="playing") # playing, cleared, failed
    last_destroyed_sword = Column(JSON, nullable=True) # 되돌리기 주문서용 마지막 파괴 검 정보
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="active_run")

class RunHistory(Base):
    __tablename__ = "run_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    best_level = Column(Integer, default=0)
    reached_round = Column(Integer, default=1)
    destroyed_count = Column(Integer, default=0)
    relics = Column(JSON, default=list)
    result = Column(String(32)) # cleared, failed
    ended_at = Column(DateTime, default=datetime.datetime.utcnow)

class EnhanceLog(Base):
    __tablename__ = "enhance_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    run_id = Column(Integer, nullable=True)
    sword_type = Column(String(32), default="normal")
    from_level = Column(Integer, nullable=False)
    to_level = Column(Integer, nullable=False)
    result = Column(String(32), nullable=False) # success, great_success, keep, destroy
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Friend(Base):
    __tablename__ = "friends"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    friend_user_id = Column(Integer, ForeignKey("users.id"), index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Ranking(Base):
    __tablename__ = "rankings"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, index=True, nullable=False)
    best_round = Column(Integer, default=1)
    best_level = Column(Integer, default=0)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    user = relationship("User", back_populates="ranking")
