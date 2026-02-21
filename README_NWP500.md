# NWP500 Support

This integration supports the Navien NWP500 heat pump water heater via the MGPP protocol. The NWP500 communicates differently from legacy Navien gas tankless heaters, so it has its own set of entities and capabilities.

---

## Supported Features

### Water Heater Entity

The NWP500 is exposed as a standard Home Assistant water heater entity with the following capabilities:

- **Operation modes:** Heat Pump, Electric, Eco, High Demand, Off
- **Target temperature control** (0.5 °C increments, within the unit's configured min/max range)
- **Away Mode** (Vacation Mode — see the [Away Mode](#away-mode) section below)
- **Power on/off**
- **Status reporting:** Current tank water temperature

### Sensors

| Sensor | Notes |
|---|---|
| DHW Charge | Tank charge percentage (0–100%) — how much hot water is left |
| Power | Instantaneous power draw in watts (disabled by default) |
| Ambient Temperature | Inlet air temperature (diagnostic, disabled by default) |
| Tank Upper Temperature | (diagnostic, disabled by default) |
| Tank Lower Temperature | (diagnostic, disabled by default) |
| Discharge Temperature | Refrigerant discharge temp (diagnostic, disabled by default) |
| Suction Temperature | Refrigerant suction temp (diagnostic, disabled by default) |
| Evaporator Temperature | (diagnostic, disabled by default) |
| WiFi Signal Strength | dBm (diagnostic, disabled by default) |
| Target Fan RPM | (diagnostic, disabled by default) |
| Current Fan RPM | (diagnostic, disabled by default) |
| Error Code / Sub Error Code | (diagnostic, disabled by default) |
| Total / Available Energy Capacity | (diagnostic, disabled by default) |
| EEV Step | Electronic expansion valve position (diagnostic, disabled by default) |
| Current / Target Superheat | (diagnostic, disabled by default) |
| Current State Number | Internal state machine value (diagnostic, disabled by default) |
| Evaporator Fan Operating Hours | Cumulative runtime (diagnostic, disabled by default) |
| Recirculation Flow Rate | Only present if the unit supports recirculation (diagnostic, disabled by default) |
| Recirculation Faucet Temperature | Only present if the unit supports recirculation (diagnostic, disabled by default) |

### Switches

| Switch | Notes |
|---|---|
| Anti-Legionella | Enables the periodic high-temperature sanitation cycle (config, disabled by default) |
| Freeze Protection | Enables freeze protection mode (config, disabled by default) |
| Hot Button | Triggers a recirculation demand; only present if the unit supports recirculation |

### Configuration Entities

| Entity | Notes |
|---|---|
| Vacation Mode Duration | Number of days for Away Mode / Vacation Mode (1–99 days) |

### Diagnostic Binary Sensors (all disabled by default)

| Sensor | Description |
|---|---|
| Upper Heating Element | Whether the upper electric element is active |
| Lower Heating Element | Whether the lower electric element is active |
| Heat Pump Compressor | Whether the compressor is running |
| Evaporator Fan | Whether the evaporator fan is running |
| Electronic Expansion Valve | Whether the EEV is active |
| System Heating | Whether the unit is actively heating |
| Hot Button Ready | Only present if the unit supports recirculation |
| Recirculation Pump | Only present if the unit supports recirculation |

---

## Unsupported Features

The following features available in the Navien app are **not** supported by this integration:

1. **Scheduling** — The NWP500 app supports configuring daily heating schedules. This integration does not expose schedule configuration. Use Home Assistant automations to change operation modes or set temperatures on a time-based schedule instead.

2. **Energy usage history** — The Navien app shows historical energy consumption data stored on the cloud. This integration only exposes real-time state and does not retrieve historical energy logs. See the [Energy Monitoring](#energy-monitoring) section below for how to approximate energy tracking in Home Assistant.

3. **Rate plans / time-of-use / demand response settings** — The Navien app provides configuration for utility rate plans, time-of-use pricing, and demand response programs. These settings cannot be read or written through this integration.

---

## Energy Monitoring

The NWP500 exposes an instantaneous **Power** sensor (in watts) that is disabled by default. To enable it, navigate to the device in Home Assistant, find the **Power** sensor entity, and enable it.

Because this sensor reports instantaneous power rather than cumulative energy, you can convert it to energy (watt-hours) using Home Assistant's built-in **Integral Sensor** helper, which applies the trapezoidal rule to numerically integrate power over time.

**To set up an Integral Sensor:**

1. Go to **Settings → Devices & Services → Helpers → Create Helper → Integral Sensor**.
2. Set the **Input Sensor** to the NWP500 Power sensor.
3. Set the **Unit prefix** to none (or "k" for kilowatt-hours) and **Unit time** to hours.
4. The resulting sensor will accumulate energy in watt-hours (or kilowatt-hours), suitable for use in the Home Assistant **Energy Dashboard**.

The trapezoidal rule used by the Integral Sensor helper approximates the area under the power curve by averaging each pair of consecutive readings and multiplying by the elapsed time. Accuracy improves with more frequent polling updates from the device.

---

## Away Mode

Away Mode in Home Assistant maps to **Vacation Mode** on the NWP500.

### Setting Up Away Mode

The **Vacation Mode Duration** configuration entry (a number entity, 1–99 days) **must be set before activating Away Mode**. This value controls how many days the unit will remain in vacation mode. Set it by finding the "Vacation Mode Duration" entity on the device page and entering the desired number of days.

Once the duration is configured, enable Away Mode by toggling the Away Mode switch in the Home Assistant water heater card or via an automation.

### How Vacation Mode Works

The NWP500 does not simply shut off during vacation mode. Instead, it ends vacation mode **9 hours before the specified duration expires**. This early-exit window allows the heat pump several hours to reheat the tank back to the normal setpoint temperature before occupants return.

For example, if you set a 7-day vacation mode, the unit will exit vacation mode and begin reheating after approximately 6 days and 15 hours.

### Vacation Mode vs. Simply Turning the Unit Off

In many circumstances, vacation mode is functionally equivalent to turning the unit off for the duration of the absence — the compressor does not run and the tank is allowed to cool. The key differences are:

- **Freeze protection:** If the unit's Freeze Protection switch is enabled, the unit retains the ability to activate the heating elements to prevent freezing even while in vacation mode. If the Freeze Protection switch is disabled, or if freezing temperatures are not a concern during the absence, vacation mode and powering off are effectively the same.
- **Anti-Seize:** If left in vacation mode for a long time, the unit will perform anti-seize to prevent the internal valves from seizing up.
- **Automatic return to service:** Vacation mode will automatically bring the unit back online before the specified end date (see above), whereas a manually powered-off unit requires a manual power-on.

If freeze protection and anti-seize features are not needed for the duration of an absence, turning the unit off via the Water Heater entity is a simpler equivalent to vacation mode.