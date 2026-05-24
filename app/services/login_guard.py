"""登录失败计数与验证码触发。"""
import secrets
import threading
from typing import Dict

_lock = threading.Lock()
_fail_counts: Dict[str, int] = {}

FAIL_THRESHOLD = 10


def get_failure_count(ip: str) -> int:
    with _lock:
        return _fail_counts.get(ip, 0)


def captcha_required(ip: str) -> bool:
    return get_failure_count(ip) >= FAIL_THRESHOLD


def record_login_failure(ip: str) -> int:
    with _lock:
        _fail_counts[ip] = _fail_counts.get(ip, 0) + 1
        return _fail_counts[ip]


def record_login_success(ip: str) -> None:
    with _lock:
        _fail_counts.pop(ip, None)
