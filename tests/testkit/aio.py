"""동기 테스트 스텝(pytest-bdd, 키워드)에서 코루틴을 실행하는 브리지."""
import asyncio


def run(coro):
    """새 이벤트 루프에서 코루틴을 끝까지 실행하고 결과를 돌려준다."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
