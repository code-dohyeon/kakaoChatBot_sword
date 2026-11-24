import asyncio
from contextlib import asynccontextmanager
from typing import Dict, AsyncGenerator

class UserLockManager:
    """
    유저별 비동기 동시성 락 관리자.
    카카오톡 챗봇 특유의 빠른 버튼 연타/중복 클릭(Double tap)으로 인한
    데이터 레이스 컨디션(동일 검 중복 강화, 골드/아이템 중복 소모 등)을 방지합니다.
    """
    _locks: Dict[str, asyncio.Lock] = {}
    _master_lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    async def get_lock(cls, user_key: str) -> asyncio.Lock:
        async with cls._master_lock:
            if user_key not in cls._locks:
                cls._locks[user_key] = asyncio.Lock()
            return cls._locks[user_key]

    @classmethod
    @asynccontextmanager
    async def acquire(cls, user_key: str, timeout: float = 0.2) -> AsyncGenerator[bool, None]:
        """
        user_key에 대한 락 획득을 시도합니다.
        timeout 내에 락을 획득하면 True를 yield하고,
        이미 다른 요청이 처리 중이어서 timeout이 발생하면 False를 yield합니다.
        """
        lock = await cls.get_lock(user_key)
        acquired = False
        try:
            await asyncio.wait_for(lock.acquire(), timeout=timeout)
            acquired = True
            yield True
        except asyncio.TimeoutError:
            # 이전 요청 처리 중 -> 연타/중복 요청 방어
            yield False
        finally:
            if acquired:
                lock.release()

    @classmethod
    def active_lock_count(cls) -> int:
        return len(cls._locks)

    @classmethod
    async def cleanup(cls):
        """미사용 락 정리 (필요 시 주기적 호출 가능)"""
        async with cls._master_lock:
            # 락이 잡혀있지 않은 항목들 정리
            to_remove = [k for k, v in cls._locks.items() if not v.locked()]
            for k in to_remove:
                del cls._locks[k]
