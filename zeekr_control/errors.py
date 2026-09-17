"""Safe client errors; never include server response bodies or credentials."""


class ApiError(Exception):
    """User-visible API error."""


class RateLimited(ApiError):
    def __init__(self, seconds):
        self.seconds = seconds
        super().__init__('网关 HTTP 429；至少等待 %d 秒后再查询，未自动重试。' % seconds)
