"""Support for Navien NaviLink sensors."""
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.helpers.entity import EntityCategory
from .navien_api import TemperatureType, MgppDevice
from .entity import NavienBaseEntity
from .migration import get_legacy_unique_id_if_exists
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
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
    """Class for temperature sensor values.
    
    Values from the API are already in the device's native unit (Celsius or Fahrenheit).
    We declare the native unit to HA, which handles display conversion.
    """
    def __init__(self, state_class, native_unit_of_measurement, name, device_class=None) -> None:
        self.state_class = state_class
        self.native_unit_of_measurement = native_unit_of_measurement
        self.name = name
        self.device_class = device_class
        # No longer need conversion_factor since values are in native unit
        self.conversion_factor = 1

    def convert(self, temp):
        # Values are already in native unit, no conversion needed
        return temp


def get_description(hass_units, navien_units, sensor_type):
    """Get sensor description based on units.
    
    For temperature sensors, values are in the device's native unit (navien_units).
    We declare that unit to HA, which handles display conversion.
    
    For gas/flow sensors, we still convert between metric/imperial as needed.
    """
    # Temperature sensors use the device's native unit
    temp_unit = UnitOfTemperature.CELSIUS if navien_units == "metric" else UnitOfTemperature.FAHRENHEIT
    
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
            native_unit_of_measurement=temp_unit,
            name="Inlet Temp",
            device_class=SensorDeviceClass.TEMPERATURE
        ),
        "currentOutletTemp": TempSensorDescription(
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=temp_unit,
            name="Hot Water Temp",
            device_class=SensorDeviceClass.TEMPERATURE
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
        device_id = device.device_identifier
        if isinstance(device, MgppDevice):
            # MGPP-specific sensors
            sensors.append(MgppSensor(coordinator, device_id, 'dhwChargePer', 'DHW Charge',
                                      unit=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT))
            
            # Diagnostic sensors - disabled by default
            sensors.extend([
                MgppSensor(coordinator, device_id, 'tankUpperTemperature', 'Tank Upper Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'tankLowerTemperature', 'Tank Lower Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'dischargeTemperature', 'Discharge Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'suctionTemperature', 'Suction Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'evaporatorTemperature', 'Evaporator Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'ambientTemperature', 'Ambient Temperature',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'wifiRssi', 'WiFi Signal Strength',
                          device_class=SensorDeviceClass.SIGNAL_STRENGTH, unit='dBm',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'currentInstPower', 'Current Instantaneous Power',
                          unit=UnitOfPower.WATT, state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                # Fan sensors
                MgppSensor(coordinator, device_id, 'targetFanRpm', 'Target Fan RPM',
                          unit='RPM', state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'currentFanRpm', 'Current Fan RPM',
                          unit='RPM', state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                # Error sensors
                MgppSensor(coordinator, device_id, 'errorCode', 'Error Code',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'subErrorCode', 'Sub Error Code',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                # Energy capacity sensors
                MgppSensor(coordinator, device_id, 'totalEnergyCapacity', 'Total Energy Capacity',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'availableEnergyCapacity', 'Available Energy Capacity',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                # Heat pump diagnostic sensors
                MgppSensor(coordinator, device_id, 'eevStep', 'EEV Step',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'currentSuperHeat', 'Current Superheat',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'targetSuperHeat', 'Target Superheat',
                          device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'currentStatenum', 'Current State Number',
                          state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
                MgppSensor(coordinator, device_id, 'cumulatedOpTimeEvaFan', 'Evaporator Fan Operating Hours',
                          device_class=SensorDeviceClass.DURATION, unit=UnitOfTime.HOURS,
                          state_class=SensorStateClass.TOTAL_INCREASING, enabled_default=False,
                          entity_category=EntityCategory.DIAGNOSTIC),
            ])
            
            # Recirculation sensors - only if device supports recirculation
            if device.supports_recirculation:
                sensors.extend([
                    MgppSensor(coordinator, device_id, 'recircDhwFlowRate', 'Recirculation Flow Rate',
                              state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                              entity_category=EntityCategory.DIAGNOSTIC),
                    MgppSensor(coordinator, device_id, 'recircFaucetTemperature', 'Recirculation Faucet Temperature',
                              device_class=SensorDeviceClass.TEMPERATURE, unit=UnitOfTemperature.CELSIUS,
                              state_class=SensorStateClass.MEASUREMENT, enabled_default=False,
                              entity_category=EntityCategory.DIAGNOSTIC),
                ])
        else:
            # Legacy sensors
            navien_units = "us_customary" if device.channel_info.get("temperatureType", 2) == TemperatureType.FAHRENHEIT.value else "metric"
            hass_units = "us_customary" if hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else "metric"
            sensors.append(NavienAvgCalorieSensor(coordinator, device_id))
            for unit_info in device.channel_status.get("unitInfo", {}).get("unitStatusList", []):
                for sensor_type in ["gasInstantUsage", "accumulatedGasUsage", "DHWFlowRate", "currentInletTemp", "currentOutletTemp"]:
                    sensors.append(NavienSensor(hass, coordinator, device_id, unit_info, sensor_type, get_description(hass_units, navien_units, sensor_type)))
    
    async_add_entities(sensors)


class NavienAvgCalorieSensor(NavienBaseEntity, SensorEntity):
    """Representation of a Navien Sensor device."""

    _attr_name = "Heating Power"

    def __init__(self, coordinator, device_identifier):
        """Initialize the sensor."""
        super().__init__(coordinator, device_identifier)
        self._cached_unique_id = None

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}{channel}avgCalorie"""
        return f"{self.device.mac_address}{self.device.channel_number}avgCalorie"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_{channel}_avg_calorie"""
        return f"{self._device_identifier}_avg_calorie"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "sensor",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

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
        return self.device.channel_status.get("avgCalorie", 0)


class NavienSensor(NavienBaseEntity, SensorEntity):
    """Representation of a Navien Sensor device."""

    def __init__(self, hass, coordinator, device_identifier, unit_info, sensor_type, sensor_description):
        """Initialize the sensor."""
        super().__init__(coordinator, device_identifier)
        self.unit_info = unit_info
        self.sensor_type = sensor_type
        self.sensor_description = sensor_description
        self.unit_number = unit_info.get("unitNumber", "")
        self.hass = hass
        self._cached_unique_id = None
        # Set name based on unit number
        if self.unit_number:
            self._attr_name = f"Unit {self.unit_number} {sensor_description.name}"
        else:
            self._attr_name = sensor_description.name

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        hass_units = "us_customary" if self.hass.config.units.temperature_unit == UnitOfTemperature.FAHRENHEIT else "metric"
        navien_units = "us_customary" if self.device.channel_info.get("temperatureType", 2) == TemperatureType.FAHRENHEIT.value else "metric"
        for unit_info in self.device.channel_status.get("unitInfo", {}).get("unitStatusList", []):
            if unit_info.get("unitNumber", "") == self.unit_number:
                self.unit_info = unit_info
        self.sensor_description = get_description(hass_units, navien_units, self.sensor_type)
        # Update name in case sensor_description.name changed
        if self.unit_number:
            self._attr_name = f"Unit {self.unit_number} {self.sensor_description.name}"
        else:
            self._attr_name = self.sensor_description.name
        self.async_write_ha_state()

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}{channel}{unit}{type}"""
        return f"{self.device.mac_address}{self.device.channel_number}{self.unit_info.get('unitNumber', '')}{self.sensor_type}"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_{channel}_{unit}_{type}"""
        return f"{self._device_identifier}_{self.unit_info.get('unitNumber', '')}_{self.sensor_type}"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "sensor",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

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

    # Mapping from sensor_key to MgppDevice property name for temperature sensors
    TEMP_PROPERTY_MAP = {
        'tankUpperTemperature': 'tank_upper_temperature',
        'tankLowerTemperature': 'tank_lower_temperature',
        'ambientTemperature': 'ambient_temperature',
        'dischargeTemperature': 'discharge_temperature',
        'suctionTemperature': 'suction_temperature',
        'evaporatorTemperature': 'evaporator_temperature',
        'currentSuperHeat': 'current_superheat',
        'targetSuperHeat': 'target_superheat',
        'recircFaucetTemperature': 'recirc_faucet_temperature',
    }

    def __init__(self, coordinator, device_identifier, sensor_key, name, device_class=None,
                 unit=None, state_class=None, enabled_default=True,
                 entity_category=None):
        super().__init__(coordinator, device_identifier)
        self.sensor_key = sensor_key
        self._attr_name = name
        self._device_class = device_class
        self._unit = unit
        self._state_class = state_class
        self._enabled_default = enabled_default
        self._attr_entity_category = entity_category
        self._cached_unique_id = None

    def _get_legacy_unique_id(self) -> str:
        """Return legacy unique_id format: {mac}{key}"""
        return f"{self.device.mac_address}{self.sensor_key}"

    def _get_new_unique_id(self) -> str:
        """Return new unique_id format: {mac}_{key}"""
        return f"{self._device_identifier}_{self.sensor_key}"

    @property
    def unique_id(self):
        """Return the unique ID of the entity, using legacy format if it exists."""
        if self._cached_unique_id is not None:
            return self._cached_unique_id
        
        if self.hass is None:
            return self._get_new_unique_id()
        
        self._cached_unique_id = get_legacy_unique_id_if_exists(
            self.hass, "sensor",
            self._get_legacy_unique_id(),
            self._get_new_unique_id(),
        )
        return self._cached_unique_id

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
        # For temperature sensors, use MgppDevice properties which handle decoding
        if self.sensor_key in self.TEMP_PROPERTY_MAP:
            prop_name = self.TEMP_PROPERTY_MAP[self.sensor_key]
            return getattr(self.device, prop_name, 0.0)

        # Return raw value for non-temperature sensors
        return self.device.channel_status.get(self.sensor_key, 0)

    @property
    def entity_registry_enabled_default(self):
        """Return if the entity should be enabled by default."""
        return self._enabled_default
