"""DataUpdateCoordinator for Kärcher Home Robots."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from karcher.device import Device, DeviceProperties
from karcher.exception import KarcherHomeAccessDenied, KarcherHomeTokenExpired
from karcher.identifiers import VacuumState

from .api import KarcherApi
from .const import (
    DOMAIN,
    POLL_INTERVAL,
    STATUS_DOCKED,
    WORK_MODE_CLEANING,
    WORK_MODE_GO_HOME,
    WORK_MODE_IDLE,
    WORK_MODE_PAUSE,
)

_LOGGER = logging.getLogger(__name__)


def derive_vacuum_state(props: DeviceProperties) -> VacuumState:
    """Map raw DeviceProperties fields to a VacuumState enum value.

    Confirmed field behaviour from traffic capture (2026-03-28):
    - ``work_mode`` is the primary state signal (not ``mode``, which stays 0).
    - ``status`` 4 = docked; ``charge_state`` > 0 also indicates docked.
    - ``fault`` non-zero can coexist with normal operation (minor warnings);
      only treat as Error when the robot is not otherwise active.
    """
    work_mode = props.work_mode

    if work_mode in WORK_MODE_CLEANING:
        return VacuumState.Cleaning

    if work_mode in WORK_MODE_GO_HOME:
        if props.status == STATUS_DOCKED or props.charge_state:
            return VacuumState.Docked
        return VacuumState.Returning

    if work_mode in WORK_MODE_PAUSE:
        return VacuumState.Paused

    if work_mode in WORK_MODE_IDLE:
        if props.status == STATUS_DOCKED or props.charge_state:
            return VacuumState.Docked
        if props.fault:
            return VacuumState.Error
        return VacuumState.Idle

    _LOGGER.debug("Unknown work_mode=%d status=%d charge_state=%d",
                  work_mode, props.status, props.charge_state)
    if props.status == STATUS_DOCKED or props.charge_state:
        return VacuumState.Docked
    return VacuumState.Unknown


class KarcherCoordinator(DataUpdateCoordinator[DeviceProperties]):
    """Coordinator that combines MQTT push with a polling fallback."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: KarcherApi,
        device: Device,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{device.sn}",
            update_interval=timedelta(seconds=POLL_INTERVAL),
        )
        self.api = api
        self.device = device

    async def _async_update_data(self) -> DeviceProperties:
        """Poll the device (fallback when MQTT push is absent)."""
        try:
            # Run the blocking request+wait in the executor.
            props = await self.hass.async_add_executor_job(
                self.api._client.get_device_properties, self.device
            )
        except KarcherHomeTokenExpired as err:
            raise ConfigEntryAuthFailed("Token expired") from err
        except KarcherHomeAccessDenied as err:
            raise ConfigEntryAuthFailed("Access denied") from err
        except AttributeError as err:
            # python-karcher has a typo: DeviceProperties.net_stauts vs net_status.
            # The data is still updated before the exception; return what we have.
            _LOGGER.debug("Ignoring net_status AttributeError from python-karcher: %s", err)
            props = self.api._client._device_props.get(self.device.sn)
            if props is None:
                raise UpdateFailed("No device data available") from err
        except Exception as err:
            raise UpdateFailed(f"Error communicating with Kärcher cloud: {err}") from err

        return props

    @callback
    def handle_mqtt_push(self, props: DeviceProperties) -> None:
        """Called (thread-safely) when MQTT delivers a property update.

        This is scheduled via hass.loop.call_soon_threadsafe so it runs
        in the HA event loop, not in the paho-mqtt thread.
        """
        self.async_set_updated_data(props)
