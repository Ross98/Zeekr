"""Safe error messages, with separate private notification context."""


class ApiError(Exception):
    """User-visible API error."""

    def __init__(self, message, http_status=None, retry_after=None, gateway_code=None, gateway_reason=None,
                 notification_reason=None, retryable=False):
        self.gateway_code = gateway_code
        self.gateway_reason = gateway_reason
        # Private Bark context only; never add this field to str(error) or health/audit output.
        self.notification_reason = gateway_reason if notification_reason is None else notification_reason
        self.http_status = http_status
        self.retryable = bool(retryable or type(http_status) is int and (http_status==408 or 500<=http_status<=599))
        self.retry_after = retry_after
        super().__init__(message)


class RateLimited(ApiError):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__('网关 HTTP 429；至少等待 %d 秒后再查询，未自动重试。' % seconds,
                         http_status=429, retry_after=seconds, retryable=True)


class RecordConflict(ValueError):
    """The requested record revision no longer matches persistent state."""


class RequestDeferred(ApiError):
    """Query protection proved that no transport callback was invoked."""
    request_sent = False
