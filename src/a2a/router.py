"""
A2A Router
----------
FastAPI router mounted by every agent service.
Exposes POST /a2a — the single entry point for peer-agent calls.

Each agent service registers its own task handlers via register_handler().

Example in an agent's app.py:

    from a2a import a2a_router, register_handler

    async def handle_search(msg: A2AMessage) -> dict:
        ...
        return {"results": [...]}

    register_handler("search", handle_search)
    app.include_router(a2a_router)
"""

import time
from collections.abc import Awaitable, Callable

import structlog
from fastapi import APIRouter

from .models import A2AMessage, A2AResponse

log = structlog.get_logger()

# Global handler registry: task_name → async callable
_handlers: dict[str, Callable[[A2AMessage], Awaitable[dict]]] = {}

a2a_router = APIRouter()


def register_handler(task: str, fn: Callable[[A2AMessage], Awaitable[dict]]) -> None:
    """Register an async handler for a given task name."""
    _handlers[task] = fn
    log.info("a2a_handler_registered", task=task)


@a2a_router.post("/a2a", response_model=A2AResponse)
async def handle_a2a(msg: A2AMessage) -> A2AResponse:
    """
    Dispatch an incoming A2A message to the registered handler.
    Returns a structured A2AResponse.
    """
    t0 = time.time()
    handler = _handlers.get(msg.task)

    if handler is None:
        known = list(_handlers.keys())
        log.warning("a2a_unknown_task", task=msg.task, known=known)
        return A2AResponse(
            agent=msg.receiver,
            status="error",
            error=f"Unknown task '{msg.task}'. Registered tasks: {known}",
        )

    log.info("a2a_dispatch", task=msg.task, sender=msg.sender)

    try:
        result = await handler(msg)
        elapsed = round((time.time() - t0) * 1000)
        return A2AResponse(
            agent=msg.receiver,
            status="ok",
            result=result,
            duration_ms=elapsed,
        )

    except Exception as exc:
        elapsed = round((time.time() - t0) * 1000)
        log.error("a2a_handler_error", task=msg.task, error=str(exc))
        return A2AResponse(
            agent=msg.receiver,
            status="error",
            error=str(exc),
            duration_ms=elapsed,
        )
