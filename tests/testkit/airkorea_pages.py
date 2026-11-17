"""에어코리아 웹 페이지(realSearch / getRealChart) 호출을 흉내 내는 가짜 aiohttp 세션."""


class PageResponse:
    def __init__(self, status=200, text="", payload=None):
        self.status, self._text, self._payload = status, text, payload

    async def text(self):
        return self._text

    async def json(self, content_type=None):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class PageSession:
    """post 호출마다 미리 정해 둔 결과를 순서대로 내놓는다 (예외 인스턴스면 raise).

    posts 에는 (url, data) 가 쌓인다. 결과를 다 쓰고도 호출되면 AssertionError.
    """

    def __init__(self, outcomes):
        self._outcomes, self.posts = list(outcomes), []

    def post(self, url, data=None, headers=None, timeout=None):
        self.posts.append((url, data))
        assert self._outcomes, "예상보다 많은 post 호출"
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False
