"""
GET /status — relay state snapshot endpoint.

Returns the current ON/OFF state of all 8 relays together with the
count of active relays and an ISO-8601 UTC timestamp.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import Settings, get_settings
from app.models.schemas import StatusResponse
from app.services.relay_service import get_relay_states
from app.utils.logger import get_logger, get_request_id

router = APIRouter(tags=["Status"])
logger = get_logger(__name__)


@router.get(
    "/status",
    response_model=StatusResponse,
    summary="Get relay status",
    description=(
        "Returns the current ON/OFF state of all 8 relays, "
        "the number of active relays, and a UTC timestamp."
    ),
)
async def get_status(
    settings: Settings = Depends(get_settings),  # noqa: ARG001
) -> StatusResponse:
    """
    Return a snapshot of the full relay state.

    This endpoint is **read-only** and never modifies relay states.
    It is safe to call from any Flutter UI polling loop.
    """
    logger.info({"event": "status_request", "request_id": get_request_id()})

    states = await get_relay_states()
    response = StatusResponse.from_relay_states(states)

    logger.info(
        {
            "event": "status_response",
            "request_id": get_request_id(),
            "active_count": response.active_count,
        }
    )
    return response
