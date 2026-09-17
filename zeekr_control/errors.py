"""Safe client errors; never include server response bodies or credentials."""


class ApiError(Exception):
    """User-visible API error."""

    def __init__(self, message, http_status=None, retry_after=None):
        self.http_status = http_status
        self.retry_after = retry_after
        super().__init__(message)


class RateLimited(ApiError):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__('网关 HTTP 429；至少等待 %d 秒后再查询，未自动重试。' % seconds)
