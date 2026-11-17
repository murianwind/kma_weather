"""동기 테스트 스텝(pytest-bdd, 키워드)에서 코루틴을 실행하는 브리지."""
import asyncio


def run(coro):
    """새 이벤트 루프에서 코루틴을 끝까지 실행하고 결과를 돌려준다."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def run_on(hass, coro):
    """hass 가 쓰는 이벤트 루프에서 코루틴을 실행한다.

    pytest-bdd 는 `async def` 스텝을 실행하지 않고 코루틴 객체만 만들어 넘기므로(조용히 통과해 버린다),
    실제 Home Assistant(hass)가 필요한 스텝은 동기 함수로 쓰고 이 함수로 코루틴을 돌린다.
    """
    return hass.loop.run_until_complete(coro)
