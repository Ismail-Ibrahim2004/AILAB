"""
Relay hardware service for the Voice AI Smart Relay Controller.

Manages 8 physical relays via RPi.GPIO (BCM mode) with a thread-safe
asyncio.Lock and automatic fallback to *simulation mode* when GPIO is
unavailable (e.g., on a development machine).

Relay state array:  relays[0..7]  →  True = ON, False = OFF
GPIO wiring:        Active-LOW board — GPIO.output(pin, not state)
"""
from __future__ import annotations

import asyncio
from typing import NamedTuple

from app.config import Settings, get_settings
from app.utils.exceptions import GPIOError, RelayIndexError
from app.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# GPIO import with simulation fallback
# ---------------------------------------------------------------------------
try:
    from gpiozero import Device, OutputDevice

    # Ensure pin factory can be loaded (fails on non-Pi hardware even if gpiozero is installed)
    Device.ensure_pin_factory()

    _GPIO_AVAILABLE = True
    logger.info({"event": "gpio_import", "status": "hardware_mode", "library": "gpiozero"})
except ImportError:
    OutputDevice = None  # type: ignore[assignment, misc]
    _GPIO_AVAILABLE = False
    logger.warning(
        {"event": "gpio_import", "status": "simulation_mode",
         "reason": "gpiozero not installed — running in SIMULATION mode."}
    )
except Exception as e:
    # Catches gpiozero.exc.BadPinFactory and similar hardware-related errors
    OutputDevice = None  # type: ignore[assignment, misc]
    _GPIO_AVAILABLE = False
    logger.warning(
        {"event": "gpio_import", "status": "simulation_mode",
         "reason": f"Hardware unavailable ({e.__class__.__name__}) — running in SIMULATION mode."}
    )


# ---------------------------------------------------------------------------
# Shared mutable state  (ONLY place allowed to hold global mutable state)
# ---------------------------------------------------------------------------
_relay_states: list[bool] = [False] * 8
_relay_lock: asyncio.Lock = asyncio.Lock()
_gpio_devices: dict[int, "OutputDevice"] = {}


# ---------------------------------------------------------------------------
# Helper NamedTuple for relay operation results
# ---------------------------------------------------------------------------

class RelayOperationResult(NamedTuple):
    """Encapsulates the outcome of a single relay operation."""

    index: int | None          # None for bulk operations
    previous_state: bool | None
    new_state: bool | None
    already_in_state: bool
    affected_indices: list[int]  # all indices touched


# ---------------------------------------------------------------------------
# Internal GPIO helpers
# ---------------------------------------------------------------------------

def _gpio_write(pin: int, state: bool, settings: Settings) -> None:
    """
    Drive a single GPIO pin to match the desired relay state.

    Args:
        pin:      BCM pin number.
        state:    Desired logical relay state (True = ON).
        settings: Application settings (reads active_low flag).

    Raises:
        GPIOError: If the GPIO output call fails.
    """
    if not _GPIO_AVAILABLE:
        logger.debug(
            {"event": "gpio_write", "mode": "SIMULATION", "pin": pin, "state": state}
        )
        return

    try:
        device = _gpio_devices.get(pin)
        if not device:
            raise GPIOError(f"Pin {pin} is not initialized as a GPIO OutputDevice.")
            
        if state:
            device.on()
        else:
            device.off()
            
        logger.debug(
            {"event": "gpio_write", "mode": "hardware", "pin": pin,
             "logical_state": state, "gpio_level": device.value}
        )
    except Exception as exc:  # noqa: BLE001
        raise GPIOError(f"GPIO write failed on pin {pin}: {exc}") from exc


def _gpio_setup(settings: Settings) -> None:
    """
    Initialise GPIO subsystem and set all relay pins as outputs.

    Args:
        settings: Application settings (reads gpio_pins_bcm).
    """
    if not _GPIO_AVAILABLE:
        logger.info({"event": "gpio_setup", "mode": "SIMULATION"})
        return

    for pin in settings.gpio_pins_bcm:
        if pin not in _gpio_devices:
            # gpiozero intercepts active_high to invert .on() / .off() seamlessly
            device = OutputDevice(
                pin, 
                active_high=not settings.gpio_active_low, 
                initial_value=False
            )
            _gpio_devices[pin] = device
            
    logger.info({"event": "gpio_setup", "mode": "hardware", "pins": settings.gpio_pins_bcm})


def _gpio_cleanup() -> None:
    """Release all GPIO resources."""
    if not _GPIO_AVAILABLE:
        logger.info({"event": "gpio_cleanup", "mode": "SIMULATION"})
        return
    for pin, device in _gpio_devices.items():
        device.close()
    _gpio_devices.clear()
    logger.info({"event": "gpio_cleanup", "mode": "hardware"})


# ---------------------------------------------------------------------------
# Public service API
# ---------------------------------------------------------------------------

def startup_gpio(settings: Settings | None = None) -> None:
    """
    Initialise GPIO and set all relays to OFF.

    Called once from the application lifespan context manager at startup.

    Args:
        settings: Optional settings override; defaults to ``get_settings()``.
    """
    settings = settings or get_settings()
    _gpio_setup(settings)
    logger.info({"event": "relay_startup", "relay_count": len(_relay_states)})


def shutdown_gpio() -> None:
    """
    Set all relays to OFF and release GPIO resources.

    Called once from the application lifespan context manager at shutdown.
    """
    settings = get_settings()
    # Drive all pins OFF synchronously (shutdown, no event loop guarantee)
    for idx, pin in enumerate(settings.gpio_pins_bcm):
        _relay_states[idx] = False
        try:
            _gpio_write(pin, False, settings)
        except GPIOError:
            pass  # Best-effort on shutdown

    _gpio_cleanup()
    logger.info({"event": "relay_shutdown"})


async def get_relay_states() -> list[bool]:
    """
    Return a snapshot of the current relay state list.

    Returns:
        A copy of the internal boolean state list (length 8).
    """
    async with _relay_lock:
        return list(_relay_states)


async def set_relay(
    index: int,
    state: bool,
    settings: Settings | None = None,
) -> RelayOperationResult:
    """
    Set a single relay to an explicit ON/OFF state.

    If the relay is already in the requested state the operation is
    skipped (idempotent) and ``already_in_state=True`` is returned.

    Args:
        index:    Zero-based relay index (0–7).
        state:    Desired state: True = ON, False = OFF.
        settings: Optional settings override.

    Returns:
        :class:`RelayOperationResult` describing the outcome.

    Raises:
        RelayIndexError: If ``index`` is outside 0–7.
        GPIOError:       If the hardware write fails.
    """
    if not (0 <= index <= 7):
        raise RelayIndexError(index)

    settings = settings or get_settings()

    async with _relay_lock:
        previous = _relay_states[index]

        if previous == state:
            logger.info(
                {"event": "relay_skipped", "index": index,
                 "state": state, "reason": "already_in_state"}
            )
            return RelayOperationResult(
                index=index,
                previous_state=previous,
                new_state=state,
                already_in_state=True,
                affected_indices=[],
            )

        pin = settings.gpio_pins_bcm[index]
        _gpio_write(pin, state, settings)
        _relay_states[index] = state

    logger.info(
        {"event": "relay_set", "index": index, "previous": previous, "new": state}
    )
    return RelayOperationResult(
        index=index,
        previous_state=previous,
        new_state=state,
        already_in_state=False,
        affected_indices=[index],
    )


async def toggle_relay(
    index: int,
    settings: Settings | None = None,
) -> RelayOperationResult:
    """
    Toggle a single relay to the opposite of its current state.

    Args:
        index:    Zero-based relay index (0–7).
        settings: Optional settings override.

    Returns:
        :class:`RelayOperationResult` describing the outcome.

    Raises:
        RelayIndexError: If ``index`` is outside 0–7.
        GPIOError:       If the hardware write fails.
    """
    if not (0 <= index <= 7):
        raise RelayIndexError(index)

    settings = settings or get_settings()

    async with _relay_lock:
        previous = _relay_states[index]
        new_state = not previous
        pin = settings.gpio_pins_bcm[index]
        _gpio_write(pin, new_state, settings)
        _relay_states[index] = new_state

    logger.info(
        {"event": "relay_toggled", "index": index,
         "previous": previous, "new": new_state}
    )
    return RelayOperationResult(
        index=index,
        previous_state=previous,
        new_state=new_state,
        already_in_state=False,
        affected_indices=[index],
    )


async def set_all_relays(
    state: bool,
    settings: Settings | None = None,
) -> RelayOperationResult:
    """
    Set ALL relays to an explicit ON/OFF state.

    Only relays that need to change are written to GPIO (idempotent
    for relays already in the target state).

    Args:
        state:    Desired state for all relays.
        settings: Optional settings override.

    Returns:
        :class:`RelayOperationResult` with ``affected_indices`` listing
        every relay that was actually changed.
    """
    settings = settings or get_settings()
    changed: list[int] = []

    async with _relay_lock:
        for idx, current in enumerate(_relay_states):
            if current != state:
                pin = settings.gpio_pins_bcm[idx]
                _gpio_write(pin, state, settings)
                _relay_states[idx] = state
                changed.append(idx)

    logger.info(
        {"event": "relay_set_all", "target_state": state, "changed": changed}
    )
    return RelayOperationResult(
        index=None,
        previous_state=None,
        new_state=state,
        already_in_state=len(changed) == 0,
        affected_indices=changed,
    )


async def toggle_all_relays(
    settings: Settings | None = None,
) -> RelayOperationResult:
    """
    Toggle every relay independently.

    Args:
        settings: Optional settings override.

    Returns:
        :class:`RelayOperationResult` with all 8 indices in
        ``affected_indices``.
    """
    settings = settings or get_settings()

    async with _relay_lock:
        for idx, current in enumerate(_relay_states):
            new_state = not current
            pin = settings.gpio_pins_bcm[idx]
            _gpio_write(pin, new_state, settings)
            _relay_states[idx] = new_state

    logger.info({"event": "relay_toggle_all"})
    return RelayOperationResult(
        index=None,
        previous_state=None,
        new_state=None,
        already_in_state=False,
        affected_indices=list(range(8)),
    )
