"""Error classifier - categorize API errors and determine recovery strategy.

15+ error types, each with a different recovery strategy.
Matching layers: HTTP status → message patterns → exception types.
"""
import enum
import re


class FailoverReason(enum.Enum):
    """Error reasons mapped to recovery strategies."""
    auth = "auth"  # temporary auth error → retry with different creds
    auth_permanent = "auth_permanent"  # permanent auth error → terminate
    billing = "billing"  # billing exhausted → terminate
    rate_limit = "rate_limit"  # rate limited → wait and retry
    overloaded = "overloaded"  # service overloaded → switch provider
    server_error = "server_error"  # server error → retry
    timeout = "timeout"  # timeout → retry
    context_overflow = "context_overflow"  # context overflow → compress
    model_not_found = "model_not_found"  # model doesn't exist → terminate
    format_error = "format_error"  # request format error → terminate
    image_too_large = "image_too_large"  # image too large → terminate
    thinking_signature = "thinking_signature"  # thinking sig error → terminate
    unknown = "unknown"  # unknown → retry


class ClassifiedError:
    """Classified error with recovery metadata."""

    def __init__(self, reason: FailoverReason, message: str, retryable: bool = False,
                 should_compress: bool = False, wait_seconds: float = 0.0):
        self.reason = reason
        self.message = message
        self.retryable = retryable
        self.should_compress = should_compress
        self.wait_seconds = wait_seconds

    @property
    def fatal(self) -> bool:
        return not self.retryable and not self.should_compress


# Message pattern matching rules
_MESSAGE_PATTERNS = [
    # (regex pattern, FailoverReason, retryable, should_compress, wait_seconds)
    (re.compile(r"context\s+length|too\s+many\s+tokens|max\s+length|超过最大长度|超出.*长度", re.I),
     FailoverReason.context_overflow, False, True, 0),
    (re.compile(r"rate\s*limit|throttled|rate increased too quickly|请求频率过高", re.I),
     FailoverReason.rate_limit, True, False, 30),
    (re.compile(r"invalid\s+(api\s+)?key|unauthorized|credential|认证失败", re.I),
     FailoverReason.auth_permanent, False, False, 0),
    (re.compile(r"billing|quota\s+exceeded|account\s+overrun|余额不足|额度", re.I),
     FailoverReason.billing, False, False, 0),
    (re.compile(r"model\s+(not\s+)?found|does\s+not\s+exist|模型不存在", re.I),
     FailoverReason.model_not_found, False, False, 0),
    (re.compile(r"image.*too\s+large|图片.*太大", re.I),
     FailoverReason.image_too_large, False, False, 0),
]

# HTTP status code mapping
_HTTP_STATUS_MAP = {
    400: 400,  # check message for context_overflow or format_error
    401: FailoverReason.auth,
    402: FailoverReason.billing,
    403: FailoverReason.auth_permanent,
    429: FailoverReason.rate_limit,
    500: FailoverReason.server_error,
    502: FailoverReason.server_error,
    503: FailoverReason.overloaded,
    529: FailoverReason.overloaded,
}


def classify_error(error: Exception, provider: str = "generic") -> ClassifiedError:
    """Classify an exception into a FailoverReason and return recovery metadata."""
    error_str = str(error)

    # Layer 1: HTTP status code
    http_status = _extract_http_status(error)
    if http_status and http_status in _HTTP_STATUS_MAP:
        mapping = _HTTP_STATUS_MAP[http_status]
        if mapping == 400:
            return _classify_400(error_str)
        return _build_classified(mapping, error_str)

    # Layer 2: message pattern matching
    for pattern, reason, retryable, should_compress, wait in _MESSAGE_PATTERNS:
        if pattern.search(error_str):
            return ClassifiedError(
                reason=reason, message=error_str,
                retryable=retryable, should_compress=should_compress,
                wait_seconds=wait,
            )

    # Layer 3: exception type matching
    timeout_types = ("ReadTimeout", "ConnectError", "SSLError", "TimeoutError", "Timeout")
    if any(t in type(error).__name__ for t in timeout_types):
        return ClassifiedError(
            reason=FailoverReason.timeout, message=error_str,
            retryable=True, should_compress=False, wait_seconds=5,
        )

    # Fallback
    return ClassifiedError(
        reason=FailoverReason.unknown, message=error_str,
        retryable=True, should_compress=False, wait_seconds=5,
    )


def _extract_http_status(error: Exception) -> int | None:
    """Try to extract HTTP status code from the error."""
    # Check common attributes
    for attr in ("status_code", "status", "response_status"):
        val = getattr(error, attr, None)
        if isinstance(val, int):
            return val
    # Check for response object
    resp = getattr(error, "response", None)
    if resp is not None:
        status = getattr(resp, "status_code", None) or getattr(resp, "status", None)
        if isinstance(status, int):
            return status
    return None


def _classify_400(error_str: str) -> ClassifiedError:
    """Classify 400 errors by checking message content."""
    if re.search(r"context|length|token|max", error_str, re.I):
        return ClassifiedError(
            reason=FailoverReason.context_overflow, message=error_str,
            retryable=False, should_compress=True, wait_seconds=0,
        )
    return ClassifiedError(
        reason=FailoverReason.format_error, message=error_str,
        retryable=False, should_compress=False, wait_seconds=0,
    )


def _build_classified(reason: FailoverReason, message: str) -> ClassifiedError:
    """Build a ClassifiedError from a reason with sensible defaults."""
    RETRYABLE = {
        FailoverReason.auth, FailoverReason.rate_limit,
        FailoverReason.server_error, FailoverReason.timeout, FailoverReason.overloaded,
    }
    COMPRESS = {FailoverReason.context_overflow}
    WAITS = {
        FailoverReason.rate_limit: 30,
        FailoverReason.overloaded: 15,
        FailoverReason.server_error: 5,
        FailoverReason.timeout: 5,
    }
    return ClassifiedError(
        reason=reason, message=message,
        retryable=reason in RETRYABLE,
        should_compress=reason in COMPRESS,
        wait_seconds=WAITS.get(reason, 0),
    )


import random


def jittered_backoff(attempt: int, base_delay: float = 5.0,
                     max_delay: float = 120.0) -> float:
    """Exponential backoff with jitter. Returns delay (caller must sleep)."""
    exponential = base_delay * (2 ** attempt)
    jitter = random.uniform(0, exponential * 0.5)
    delay = min(exponential + jitter, max_delay)
    return delay
