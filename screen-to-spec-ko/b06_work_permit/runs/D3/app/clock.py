from datetime import datetime

_override = None


def now() -> datetime:
    """현재 시각(로컬, naive). 테스트에서 set_now 로 고정할 수 있다."""
    return _override or datetime.now().replace(microsecond=0)


def set_now(dt):
    global _override
    _override = dt
