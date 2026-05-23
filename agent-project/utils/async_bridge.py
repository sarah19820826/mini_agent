"""Async bridge - run async functions synchronously."""
import asyncio


def run_async(coro):
    """Run an async coroutine in a synchronous context."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
