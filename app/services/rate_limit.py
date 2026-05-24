"""轻量内存限流，防止飞书推送与行情查询被滥用。"""
import threading
import time
from collections import defaultdict
from typing import Dict, List, Tuple

from flask import has_request_context, request

_lock = threading.Lock()
_hits: Dict[str, List[float]] = defaultdict(list)


def get_client_ip() -> str:
    if has_request_context():
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr or "unknown"
    return "system"


def consume_rate_limit(key: str, max_calls: int, window_seconds: int) -> Tuple[bool, int]:
    """检查并记录一次调用。返回 (是否允许, 建议 retry_after 秒)。"""
    now = time.time()
    window_start = now - window_seconds

    with _lock:
        bucket = _hits[key]
        bucket[:] = [ts for ts in bucket if ts >= window_start]

        if len(bucket) >= max_calls:
            oldest = bucket[0]
            retry_after = max(1, int(window_seconds - (now - oldest)))
            return False, retry_after

        bucket.append(now)
        return True, 0


def rate_limit_response_message(retry_after: int) -> str:
    return f"请求过于频繁，请 {retry_after} 秒后再试"
