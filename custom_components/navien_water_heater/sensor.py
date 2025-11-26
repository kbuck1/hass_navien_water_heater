"""Support for Navien NaviLink sensors."""
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from .navien_api import TemperatureType, MgppDevice
from .mgpp_utils import to_celsius_debug
from .entity import NavienBaseEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfVolume,
)

POWER_KCAL_PER_HOUR = 'kcal/hr'
FLOW_GALLONS_PER_MIN = 'gal/min'
FLOW_LITERS_PER_MIN = 'liters/min'

from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType
from .const import DOMAIN
import logging

_LOGGER = logging.getLogger(__name__)


class GenericSensorDescription():
    """Class to convert values from metric to imperial and vice versa"""
    def __init__(self, state_class, native_unit_of_measurement, name, conversion_factor, device_class=None) -> None:
        self.state_class = state_class
        self.native_unit_of_measurement = native_unit_of_measurement
        self.name = name
        self.conversion_factor = conversion_factor
        self.device_class = device_class

    def convert(self, val):
        return round(val * self.conversion_factor, 1)


class TempSensorDescription():
    """Class to convert temperature values"""
    def __init__(self, state_class, native_unit_of_measurement, name, convert_to, device_class=None) -> None:
        self.state_class = state_class
        self.native_unit_of_measurement = native_unit_of_measurement
        self.name = name
        self.convert_to = convert_to
        self.device_class = device_class

    def convert(self, temp):
        if self.convert_to == UnitOfTemperature.CELSIUS:
            return round((temp - 32) * 5 / 9, 1)
        elif self.convert_to == UnitOfTemperature.FAHRENHEIT:
            return round((temp * 9 / 5) + 32)
        else:
            return temp


def get_description(hass_units, navien_units, sensor_type):
    return {
        "gasInstantUsage": GenericSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=POWER_KCAL_PER_HOUR if hass_units == "metric" else UnitOfPower.BTU_PER_HOUR,
            name="Current Gas Use",
            conversion_factor=1 if hass_units == navien_units else 3.96567 if hass_units == "us_customary" else 0.2521646022
        ),
        "accumulatedGasUsage": GenericSensorDescription(
            state_class=SensorStateClass.TOTAL_INCREASING,
            native_unit_of_measurement=UnitOfVolume.CUBIC_METERS if hass_units == "metric" else UnitOfVolume.CUBIC_FEET,
            name="Cumulative Gas Use",
            conversion_factor=1 if hass_units == navien_units else 35.3147 if hass_units == "us_customary" else 0.0283168732,
            device_class=SensorDeviceClass.GAS
        ),
        "DHWFlowRate": GenericSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=FLOW_LITERS_PER_MIN if hass_units == "metric" else FLOW_GALLONS_PER_MIN,
            name="Hot Water Flow",
            conversion_factor=1 if hass_units == navien_units else 0.264172 if hass_units == "us_customary" else 3.78541
        ),
        "currentInletTemp": TempSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS if hass_units == "metric" else UnitOfTemperature.FAHRENHEIT,
            name="Inlet Temp",
            convert_to="None" if hass_units == navien_units else UnitOfTemperature.FAHRENHEIT if hass_units == "us_customary" else UnitOfTemperature.CELSIUS
        ),
        "currentOutletTemp": TempSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=UnitOfTemperature.CELSIUS if hass_units == "metric" else UnitOfTemperature.FAHRENHEIT,
            name="Hot Water Temp",
            convert_to="None" if hass_units == navien_units else UnitOfTemperature.FAHRENHEIT if hass_units == "us_customary" else UnitOfTemperature.CELSIUS
        )
    }.get(sensor_type, {})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Navien sensor."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
    sensors = []
    
    for device in coordinator.devices.values():
        if isinstance(device, MgppDevice):
            # MGPP-specific sensors
            sensors.append(MgppSensor(device, 'dhwChargePer', 'DHW Charge',
                                      unit=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT))
            
            # Diagnostic sensors - disabled by default
            sensors.extend([
                MgppSensor(device, 'tankUpperTemperature', 'Tank Upper Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
                MgppSensor(device, 'tankLowerTemperature', 'Tank Lower Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
                MgppSensor(device, 'dischargeTemperature', 'Discharge Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
                MgppSensor(device, 'suctionTemperature', 'Suction Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
                MgppSensor(device, 'evaporatorTemperature', 'Evaporator Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
                MgppSensor(device, 'ambientTemperature', 'Ambient Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
                MgppSensor(device, 'wifiRssi', 'WiFi Signal Strength',
                          device_class=SensorDeviceClass.SIGNAL_STRENGTH, unit='dBm',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
                MgppSensor(device, 'currentInstPower', 'Current Instantaneous Power',
                          unit=UnitOfPower.WATT, state_class=SensorStateClass.MEASUREMENT, enabled_default=False),
            ])
        else:
            # Legacy sensors
            navien_units = "us_customary" if device.channel_info.get("temperatureType", 2) == TemperatureType.FAHRENHEIT.value else "metric"
            hass_units = "us_customary" if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else "metric"
            sensors.append(NavienAvgCalorieSensor(device))
            for unit_info in device.channel_status.get("unitInfo", {}).get("unitStatusList", []):
                for sensor_type in ["gasInstantUsage", "accumulatedGasUsage", "DHWFlowRate", "currentInletTemp", "currentOutletTemp"]:
                    sensors.append(NavienSensor(hass, device, unit_info, sensor_type, get_description(hass_units, navien_units, sensor_type)))
    
    async_add_entities(sensors)


class NavienAvgCalorieSensor(NavienBaseEntity, SensorEntity):
    """Representation of a Navien Sensor device."""

    _attr_name = "Heating Power"

    def __init__(self, device):
        """Initialize the sensor."""
        super().__init__(device)

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return f"{self._device.device_identifier}_avg_calorie"

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the class of this entity."""
        return SensorDeviceClass.POWER_FACTOR

    @property
    def state_class(self) -> SensorStateClass:
        """Return the state class of this entity, if any."""
        return SensorStateClass.MEASUREMENT

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return PERCENTAGE

    @property
    def native_value(self) -> StateType:
        """Return the value reported by the sensor."""
        return self._device.channel_status.get("avgCalorie", 0)


class NavienSensor(NavienBaseEntity, SensorEntity):
    """Representation of a Navien Sensor device."""

    def __init__(self, hass, device, unit_info, sensor_type, sensor_description):
        """Initialize the sensor."""
        super().__init__(device)
        self.unit_info = unit_info
        self.sensor_type = sensor_type
        self.sensor_description = sensor_description
        self.unit_number = unit_info.get("unitNumber", "")
        self.hass = hass
        # Set name based on unit number
        if self.unit_number:
            self._attr_name = f"Unit {self.unit_number} {sensor_description.name}"
        else:
            self._attr_name = sensor_description.name

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        hass_units = "us_customary" if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else "metric"
        navien_units = "us_customary" if self._device.channel_info.get("temperatureType", 2) == TemperatureType.FAHRENHEIT.value else "metric"
        for unit_info in self._device.channel_status.get("unitInfo", {}).get("unitStatusList", []):
            if unit_info.get("unitNumber", "") == self.unit_number:
                self.unit_info = unit_info
        self.sensor_description = get_description(hass_units, navien_units, self.sensor_type)
        # Update name in case sensor_description.name changed
        if self.unit_number:
            self._attr_name = f"Unit {self.unit_number} {self.sensor_description.name}"
        else:
            self._attr_name = self.sensor_description.name
        self.async_write_ha_state()

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return f"{self._device.device_identifier}_{self.unit_info.get('unitNumber', '')}_{self.sensor_type}"

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the class of this entity."""
        return self.sensor_description.device_class

    @property
    def state_class(self) -> SensorStateClass:
        """Return the state class of this entity, if any."""
        return self.sensor_description.state_class

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self.sensor_description.native_unit_of_measurement

    @property
    def native_value(self) -> StateType:
        """Return the value reported by the sensor."""
        return self.sensor_description.convert(self.unit_info.get(self.sensor_type, 0))


class MgppSensor(NavienBaseEntity, SensorEntity):
    """Representation of an MGPP-specific sensor"""

    def __init__(self, device, sensor_key, name, device_class=None,
                 unit=None, state_class=None, enabled_default=True):
        super().__init__(device)
        self.sensor_key = sensor_key
        self._attr_name = name
        self._device_class = device_class
        self._unit = unit
        self._state_class = state_class
        self._enabled_default = enabled_default

    @property
    def unique_id(self):
        """Return the unique ID of the entity."""
        return f"{self._device.device_identifier}_{self.sensor_key}"

    @property
    def device_class(self) -> SensorDeviceClass:
        """Return the class of this entity."""
        return self._device_class

    @property
    def state_class(self) -> SensorStateClass:
        """Return the state class of this entity, if any."""
        return self._state_class

    @property
    def native_unit_of_measurement(self):
        """Return the unit of measurement of this entity, if any."""
        return self._unit

    @property
    def native_value(self) -> StateType:
        """Return the value reported by the sensor."""
        raw_value = self._device.channel_status.get(self.sensor_key, 0)

        # Apply temperature conversion for diagnostic temperature sensors
        if self._device_class == SensorDeviceClass.TEMPERATURE:
            return to_celsius_debug(raw_value)

        # Return raw value for non-temperature sensors
        return raw_value

    @property
    def entity_registry_enabled_default(self):
        """Return if the entity should be enabled by default."""
        return self._enabled_default
