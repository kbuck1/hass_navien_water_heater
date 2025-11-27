# Legacy Protocol (Protocol Version 1) API Reference

## Overview

This document describes the Navilink “legacy” MQTT protocol (protocolVersion 1) that predates MGPP. The content below is derived from the Android application classes under `com/kdnavien/navilink`, specifically the `mqttData` package that models every request and response handled by the app.

---

## Table of Contents

1. [MQTT Topics and Endpoints](#mqtt-topics-and-endpoints)
2. [Message Format](#message-format)
3. [Request Structure](#request-structure)
4. [Control Commands](#control-commands)
5. [Response Structure](#response-structure)
6. [Response Payloads](#response-payloads)
7. [Common Enum Values](#common-enum-values)
8. [Temperature & Unit Conventions](#temperature--unit-conventions)
9. [Events, Errors, and Last Will](#events-errors-and-last-will)
10. [Revision History](#revision-history)

---

## MQTT Topics and Endpoints

### Publish Topic Patterns

| Purpose | Topic format | Notes |
|---------|--------------|-------|
| Status / information requests | `cmd/{deviceType}/navilink-{macAddress}/status/{endpoint}` | Used for handshake, status, schedules, firmware download, and trend queries. |
| Control commands | `cmd/{deviceType}/navilink-{macAddress}/control` | All protocol v1 control flows post to `control`. |

### Subscribe Topic Patterns

| Purpose | Topic format | Notes |
|---------|--------------|-------|
| General responses | `cmd/{deviceType}/{homeSeq}/{userSeq}/{clientId}/res/{endpoint}` | `endpoint` matches the request suffix, except for `status/start` (see below). |
| Control failure events | `cmd/{deviceType}/navilink-{macAddress}/res/controlfail` | Delivers `ControlFailEvent` payloads. |
| Disconnection events | `evt/+/mobile/event/disconnect-mqtt` | Raised by the backend when MQTT connectivity drops. |
| Connection lifecycle (app last will) | `evt/{deviceType}/navilink-{macAddress}/connection` | See [Events, Errors, and Last Will](#events-errors-and-last-will). |

> **Special case:** the app maps the `status/start` request to the `res/channelinfo` response channel (see `createSubResponseTopicMessage`). Subscribe to `.../res/channelinfo` before sending `status/start`.

### Endpoint to Command ID Mapping

All command IDs are defined in `SendRequestData` and `KDEnum`. Multiple logical operations may share the same ID (context is implied by the topic postfix).

| Request endpoint (`status/*`) | Response endpoint | Command ID | Description |
|-------------------------------|-------------------|------------|-------------|
| `start` | `res/channelinfo` | `0x1000001` (16777217) | Session bootstrap; returns channel metadata. |
| `end` | `res/end` | `0x1000002` (16777218) | Terminates a session. |
| `channelinfo` | `res/channelinfo` | `0x1000003` (16777219) | Retrieves channel capability information. |
| `channelstatus` | `res/channelstatus` | `0x1000004` (16777220) | Returns detailed per-unit operational status. |
| `weeklyschedule` | `res/weeklyschedule` | `0x1000006` (16777222) | Reads weekly reservation schedules. |
| `download-sw-info` | `res/download-sw-info` | `0x1000006` (16777222) | Lists downloadable firmware packages. |
| `simpletrend` | `res/simpletrend` | `0x1000007` (16777223) | Aggregated usage counters (see `KDTrendSample`). |
| `hourlytrend` | `res/hourlytrend` | `0x1000008` (16777224) | Hourly trend slices. |
| `dailytrend` | `res/dailytrend` | `0x1000009` (16777225) | Daily trend slices. |
| `monthlytrend` | `res/monthlytrend` | `0x100000A` (16777226) | Monthly trend slices. |

### Default Subscription Set

For protocol v1 devices (deviceType ≠ 52) the app subscribes to:

- `res/channelinfo`
- `res/controlfail`
- `res/channelstatus`
- `res/weeklyschedule`
- `res/simpletrend`
- `res/hourlytrend`
- `res/dailytrend`
- `res/monthlytrend`
- `res/download-sw-info`
- `evt/{deviceType}/navilink-{macAddress}/connection`
- `evt/+/mobile/event/disconnect-mqtt`

---

## Message Format

### `PublishMessage`

Every MQTT payload published by the app is wrapped in `PublishMessage<T>`:

```json
{
  "protocolVersion": 1,
  "clientID": "uuid",
  "sessionID": "ms-since-epoch",
  "requestTopic": "cmd/{deviceType}/navilink-{mac}/status/channelinfo",
  "responseTopic": "cmd/{deviceType}/{homeSeq}/{userSeq}/{clientId}/res/channelinfo",
  "request": { /* Request specific payload */ }
}
```

### Status / Trend Requests (`Request<T>`)

```json
{
  "command": 16777219,
  "deviceType": 50,
  "macAddress": "047863593958",
  "additionalValue": "5089",
  "status": { /* see request variants below */ }
}
```

### Control Requests (`RequestControl<T>`)

```json
{
  "command": 33554435,
  "deviceType": 50,
  "macAddress": "047863593958",
  "additionalValue": "5089",
  "control": {
    "channelNumber": 1,
    "mode": "DHWTemperature",
    "param": [114]
  }
}
```

### Weekly Control Payload (`WeeklyControlData`)

```json
{
  "command": 33554438,
  "deviceType": 50,
  "macAddress": "047863593958",
  "additionalValue": "5089",
  "control": {
    "channelNumber": 1,
    "weeklyControl": 2,
    "weeklyScheduleList": [
      {
        "day": 2,
        "schdCnt": 2,
        "schdList": [
          { "num": 1, "hh": 6, "mm": 0, "flag": 1 },
          { "num": 2, "hh": 18, "mm": 0, "flag": 2 }
        ]
      }
    ]
  }
}
```

---

## Request Structure

### Common Fields

| Field | Type | Description |
|-------|------|-------------|
| `command` | `int` | Command ID assigned in `KDEnum` / `SendRequestData`. |
| `deviceType` | `int` | Device type constant (e.g. 1 = Navilink, 50 = NPF700 main). |
| `macAddress` | `string` | Device MAC (without delimiters). |
| `additionalValue` | `string` | Auxiliary identifier used by backend APIs. |

### Request Variants

#### Session Start (`status/start`)

Empty payload (`status` omitted). Use to prime channel subscriptions; response contains `KDResponseChannelInformation`.

#### Session End (`status/end`)

Same structure as start; command `0x1000002`. No payload.

#### Channel Info (`status/channelinfo`)

No additional fields. Response: `KDResponseChannelInformation`.

#### Channel Status (`status/channelstatus`)

`status` is a `RequestChannelStatus`:

```json
{
  "channelNumber": 1,
  "unitNumberStart": 1,
  "unitNumberEnd": 3
}
```

`unitNumberStart` always begins at 1; `unitNumberEnd` equals the unit count returned in channel info.

#### Weekly Schedule (`status/weeklyschedule`)

`status` is `Requestweeklyschedule` `{ "channelNumber": 1 }`.

#### Firmware Download Info (`status/download-sw-info`)

No additional payload; the shared command ID `0x1000006` tells the backend to return `KDResponseFirmwareInfo`.

#### Trend Requests (`status/simpletrend`, `hourlytrend`, `dailytrend`, `monthlytrend`)

Use `SendRequestData.getSendEMSData` payloads:

- **Simple trend (`Request`)**: no body; uses channel/unit values captured during previous status call.
- **Hourly trend (`RequesthourlyTrend`)**:

  ```json
  {
    "channelNumber": 1,
    "unitNumberStart": 1,
    "unitNumberEnd": 3,
    "year": 2024,
    "month": 9,
    "date": 24
  }
  ```

- **Daily trend (`RequestdailyTrend`)**: same as hourly, but without `date`.
- **Monthly trend (`RequestmonthlyTrend`)**:

  ```json
  {
    "channelNumber": 1,
    "unitNumberStart": 1,
    "unitNumberEnd": 3,
    "start": { "year": 2023, "month": 12 },
    "end": { "year": 2024, "month": 12 }
  }
  ```

---

## Control Commands

`KDEnum.DeviceControl` enumerates protocol v1 control operations. All commands publish to `.../control` with the `RequestControl` structure described above. Unless noted, parameters are integer arrays (`param`) whose semantics match the UI.

> **Important:** Navien APIs consistently use 0 = UNKNOWN, 1 = ON, 2 = OFF for boolean state flags. See [Common Enum Values](#common-enum-values) for complete reference.

| Enum | Command ID | `control.mode` | `param` payload | Notes |
|------|------------|----------------|-----------------|-------|
| `POWER` | 33554433 | `"power"` | `[state]` where `state` is 1 (ON) or 2 (OFF). |
| `HEAT` | 33554434 | `"heat"` | `[state]` where `state` is 1 (ON) or 2 (OFF). |
| `WATER_TEMPERATURE` | 33554435 | `"DHWTemperature"` | `[value]` (see temperature encoding). |
| `HEATTING_WATER_TEMPERATURE` | 33554436 | `"heatTemperature"` | `[value]` encoded like DHW. |
| `ON_DEMAND` | 33554437 | `"onDemand"` | `[flag]` where 1 = ON, 2 = OFF, 3 = WARMUP. |
| `WEEKLY` | 33554438 | *n/a* | `WeeklyControlData` (see example above). |
| `RECIRCULATION_TEMPERATURE` | 33554439 | `"recirculation"` | `[value]` (encoded temperature for recirculation loop). |
| `CIP_PERIOD` | 33554440 | `"CIPOperationTime"` | `[hours, minutes]` (clean-in-place runtime). |
| `CIP_RESET` | 33554443 | `"CIPSolutionReset"` | `[]` (no parameters). |
| `FILTER_RESET` | 33554444 | `"filterLifeReset"` | `[]`. |

### Weekly Schedule Helpers

`SendRequestData.getSendWeeklyData` populates schedule entries from either:

- Raw `KDDay`/`KDWeekly` entities returned by `status/weeklyschedule`, or
- UI selections converted to a list of `KDWeekly.DayOfWeek` flags (1–9).

Each `KDWeekly` entry contains:

| Field | Type | Meaning |
|-------|------|---------|
| `num` | `int` | Schedule index (1-based). |
| `hh` | `int` | Hour (0–23). |
| `mm` | `int` | Minute (0–59). |
| `flag` | `int` | Mode flag (application-defined). |

---

## Response Structure

Every MQTT response delivered to the app conforms to `ControlFailData` or `PublishMessage` with a `response` body. Core fields in `KDResponse`:

| Field | Type | Description |
|-------|------|-------------|
| `countryCD` | `int` | Country code returned by device. |
| `deviceID` | `string` | Echoed MAC address. |
| `additionalValue` | `string` | Echoed additional value. |
| `swVersion` | `int` | Firmware version. |
| `controlType` | `KDEnum.ControlType` | Inferred from response topic (channel info, state, trend, weekly, or error). |

The sections below summarize payload shapes for each endpoint.

---

## Response Payloads

### Channel Information (`KDResponseChannelInformation`)

Top-level fields:

| Field | Type | Description |
|-------|------|-------------|
| `channelCount` | `int` | Total logical channels exposed. |
| `channelUse` | `KDEnum.ChannelUse` | Bitmask of active channels. |
| `channelInformation[]` | `Channel` | Per-channel capability descriptors. |

`Channel` fields (selected):

- `channelNumber`, `unitCount`
- `unitType` (`KDEnum.unitType`)
- `temperatureType` (`KDEnum.TemperatureType`)
- `setupDHWTempMin` / `Max`
- `setupHeatTempMin` / `Max`
- `reCirculationSetupTempMin` / `Max`
- Feature toggles expressed as enums:
  - `onDemandUse` (`KDEnum.OnDemandFlag`)
  - `heatControl` (`KDEnum.heatControl`)
  - `wwsd` (winter warm start disable) (`KDEnum.wwsd`)
  - `commercialLock` (`KDEnum.commercialLockFlag`)
  - `DHWTankSensorUse` (`KDEnum.NFBWaterFlag`)
  - `recirculationUse` (`KDEnum.RecirculationFlag`)
  - `highTempDHWUse` (`KDEnum.highTempDHWUse`)
  - `DHWUse` (`KDEnum.OnOFFFlag`)
  - `freezeProtectionUse` (`KDEnum.OnOFFFlag`)
- DIP switch snapshots: `panelDipSwitchInfo`, `mainDipSwitchInfo`

### Channel Status (`KDResponseStatus`)

Top-level status:

| Field | Type | Description |
|-------|------|-------------|
| `currentChannel` | `int` | Channel index returned in the response. |
| `unitType` | `KDEnum.unitType` | Mirrors channel info. |
| `unitCount`, `operationUnitCount` | `int` | Total and active unit counts. |
| `weeklyControl` | `KDEnum.OnOFFFlag` | Weekly control active flag. |
| `powerStatus`, `heatStatus`, `onDemandUse` | `KDEnum.OnOFFFlag` | Primary mode toggles. |
| `hotWaterSettingTemperature`, `heatSettingTemperature` | `int` | Raw setpoints (see encoding). |
| `hotWaterAverageTemperature`, `inletAverageTemperature`, `supplyAverageTemperature`, `returnAverageTemperature` | `int` | Aggregated sensor data. |
| `recirculationSettingTemperature` | `int` | Recirculation target. |
| `outdoorTemperature` | `int` | Ambient reading (divide by 10 for °C). |
| `totalDayCount`, `avgCalorie` | `int` | Usage statistics. |
| `dayList[]` | `KDDay` | Weekly schedule snapshot (mirrors weekly schedule response). |
| `unitStatusList[]` | `UnitStatus` | Per-unit state (length == `unitCount`). |

`UnitStatus` (excerpt of key properties):

- Identification: `deviceNumber`, `controllerVersion`, `panelVersion`, `dipSwitchInfo`
- Faults: `errorCode`, `subErrorCode`, `filterStatus`, `filterChange`, `freezeProtectionStatus`
- Demand response: `PoEStatus`, `CIPStatus`, `CIPSolutionSupplement`
- Sensors: `currentWorkingFluidTemperature`, `currentReturnWaterTemperature`, `currentSupplyAirTemp`, `currentReturnAirTemp`
- Water: `hotWaterCurrentTemperature`, `hotWaterFlowRate`, `accumulatedWaterUsage`
- Energy: `gasInstantUse`, `gasAccumulatedUse`, `heatAccumulatedUse` (trend-aggregated)
- Recirculation: `recirculationCurrentTemperature`
- CIP: `CIPSolutionRemained`, `CIPOperationTimeHour`, `CIPOperationTimeMin`

### Weekly Schedule Response

Embedded in both `KDResponseStatus` (`dayList`) and dedicated weekly responses (`res/weeklyschedule`). Each entry is a `KDDay`:

| Field | Type | Description |
|-------|------|-------------|
| `day` | `int` | `KDWeekly.DayOfWeek` id (1 = Sunday). |
| `schdCnt` | `int` | Schedule count for the day. |
| `schdList[]` | `KDWeekly` | Individual reservations (see [Weekly Control Helpers](#weekly-control-helpers)). |

### Trend Responses

#### Simple Trend (`KDTrendSample`)

| Field | Type | Description |
|-------|------|-------------|
| `currentChannel`, `unitCount`, `unitType` | | Identifiers for the payload. |
| `totalOperatedTime`, `totalCHOperatedTime`, `totalDHWUsageTime` | `int` (minutes) | Cumulative run times. |
| `totalGasAccumulateSum` | `int` | Raw gas usage counter. |
| `totalHotWaterAccumulateSum` | `int` | Raw DHW usage counter. |
| `accumulatedWaterUsage` | `float` | Stored in deciliters (convert via [Temperature & Unit Conventions](#temperature--unit-conventions)). |
| `currentOutputTDSValue`, `currentInputTDSValue` | `int` | TDS readings. |

#### Hourly / Daily / Monthly Trend (`KDTrendDay`, `KDTrendMonth`, `KDTrendYear`)

Common structure:

- `currentChannel`, `unitCount`, `unitType`
- `unitTrendLists[]` (per-unit container)
  - `unitNumber`, `totalTrendCount`
  - `trendDataList[]` array of `TrendData`

`TrendData` fields (raw values):

| Field | Type | Units / Notes |
|-------|------|----------------|
| `sequence` | `int` | Hour index (0–23) or day index (1–31). |
| `modelInfo` | `int` | Device model metadata. |
| `gasAccumulatedUse` | `long` | Raw counter (convert using helper methods). |
| `hotWaterAccumulatedUse`, `accumulatedWaterUsage` | `long` | Stored in liters ×10 for metric devices. |
| `heatAccumulatedUse` | `long` | Electric heater consumption counter. |
| `hotWaterOperatedCount` | `int` | Operation count (×10). |
| `onDemandUseCount` | `int` | On-demand activations (×10). |
| `outdoorAirMaxTemperature`, `outdoorAirMinTemperature` | `int` | Raw temperature (divide per section below). |
| `avgInputTDSValue`, `avgOutputTDSValue` | `long` | Averages over the bucket. |
| `year`, `month`, `date` | `int` | Present in daily/monthly payloads. |

#### Monthly Trend (`KDTrendYear`)

The yearly structure mirrors `KDTrendMonth`, but aggregates by year boundaries rather than per-unit daily granularity.

### Firmware Download Info (`KDResponseFirmwareInfo`)

| Field | Type | Description |
|-------|------|-------------|
| `countryCode`, `deviceType` | `int` | Metadata echoed by backend. |
| `macAddress`, `additionalValue` | `string` | Echoed identifiers. |
| `downloadSwInfoList[]` | `DownloadSwInfo` | Firmware bundle records. |

`DownloadSwInfo` fields:

- `channelNumber`
- `swCode`
- `otaMode`
- `swVersion`
- `status`

### Control Failure (`ControlFailData` / `ControlFailEvent`)

Posted to `res/controlfail` when a control request is rejected.

| Field | Type | Description |
|-------|------|-------------|
| `protocolVersion` | `int` | Always `1`. |
| `requestTopic` | `string` | Topic that triggered the error. |
| `response.failCode` | `int` | Application-specific error code. |
| `response.deviceType`, `response.macAddress`, `response.additionalValue` | | Echoed identifiers. |

---

## Common Enum Values

Navien APIs use consistent integer values for state flags and enums. The pattern `0 = UNKNOWN, 1 = ON/first state, 2 = OFF/second state` is used throughout.

### On/Off Flags (`KDEnum.OnOFFFlag`)

| Value | Name | Description |
|-------|------|-------------|
| 0 | UNKNOWN | State unknown or not applicable |
| 1 | ON | Enabled/active |
| 2 | OFF | Disabled/inactive |

Used by: `powerStatus`, `heatStatus`, `weeklyControl`, `DHWUse`, `freezeProtectionUse`, and other boolean status fields.

### On-Demand Flags (`KDEnum.OnDemandFlag`)

| Value | Name | Description |
|-------|------|-------------|
| 0 | UNKNOWN | State unknown |
| 1 | ON | On-demand active |
| 2 | OFF | On-demand inactive |
| 3 | WARMUP | Warmup/preheat mode |

### Recirculation Flags (`KDEnum.RecirculationFlag`)

| Value | Name | Description |
|-------|------|-------------|
| 1 | ON | Recirculation enabled |
| 2 | OFF | Recirculation disabled |

### Recirculation Use (`KDEnum.RecirculationUse`)

| Value | Name | Description |
|-------|------|-------------|
| 1 | NOT_USE | Recirculation not in use |
| 2 | USE | Recirculation in use |

### NFB Water Flag (`KDEnum.NFBWaterFlag`)

| Value | Name | Description |
|-------|------|-------------|
| 1 | ON | DHW tank sensor enabled |
| 2 | OFF | DHW tank sensor disabled |

### Commercial Lock Flag (`KDEnum.commercialLockFlag`)

| Value | Name | Description |
|-------|------|-------------|
| 1 | ON | Commercial lock enabled |
| 2 | OFF | Commercial lock disabled |

### WWSD Flag (`KDEnum.wwsd`)

| Value | Name | Description |
|-------|------|-------------|
| 1 | OK | Winter warm start enabled |
| 2 | OFF | Winter warm start disabled |

### High Temp DHW Use (`KDEnum.highTempDHWUse`)

| Value | Name | Description |
|-------|------|-------------|
| 1 | TEMPERATURE_83 | 83°C high temp mode |
| 2 | TEMPERATURE_60 | 60°C standard mode |

### Temperature Type (`KDEnum.TemperatureType`)

| Value | Name | Description |
|-------|------|-------------|
| 0 | UNKNOWN | Temperature type not set |
| 1 | CELSIUS | Metric (°C) |
| 2 | FAHRENHEIT | Imperial (°F) |

### Channel Use (`KDEnum.ChannelUse`)

| Value | Name | Description |
|-------|------|-------------|
| 0 | UNKNOWN | No channels active |
| 1 | CHANNEL_1_USE | Channel 1 only |
| 2 | CHANNEL_2_USE | Channel 2 only |
| 3 | CHANNEL_1_2_USE | Channels 1 and 2 |
| 4 | CHANNEL_3_USE | Channel 3 only |
| 5 | CHANNEL_1_3_USE | Channels 1 and 3 |
| 6 | CHANNEL_2_3_USE | Channels 2 and 3 |
| 7 | CHANNEL_1_2_3_USE | All channels |

### Filter Change (`KDEnum.FilterChange`)

| Value | Name | Description |
|-------|------|-------------|
| 0 | NORMAL | Normal operation |
| 1 | REPLACE_NEED | Filter replacement needed |
| 2 | UNKNOWN | Status unknown |

---

## Temperature & Unit Conventions

The legacy protocol reuses several encoding rules that differ by context:

- **Setpoints (DHW, heating, recirculation):** when the UI is in Celsius (`temperatureType == CELSIUS`), values are transmitted as half-degree increments (`raw = °C × 2`). In Fahrenheit mode the raw value equals the displayed °F.
- **Sensor temperatures (status/trend fields such as ambient, supply, return):** stored as tenths of a degree Celsius. Convert via `value / 10`.
- **Water volumes (`TrendData.getAccumulatedWaterUsage(boolean metric)`):** metric devices use liters ×10; imperial devices use gallons (scaled per `TrendData` helper).
- **Gas usage (`TrendData.getGasAccumulatedUse`):** conversion requires device type and fuel constants; see helper methods in `TrendData`.

When building control payloads, always reuse the encoding the app itself applies (see `ControlFragment` logic for temperature rounding rules).

---

## Events, Errors, and Last Will

### Application Connection Events

The app publishes a last-will message to `evt/{deviceType}/navilink-{macAddress}/app-connection` with `RequestLastWill`:

```json
{
  "protocolVersion": 1,
  "clientID": "uuid",
  "sessionID": "ms-since-epoch",
  "requestTopic": "evt/{deviceType}/navilink-{macAddress}/app-connection",
  "event": {
    "deviceType": 50,
    "macAddress": "047863593958",
    "additionalValue": "5089",
    "connection": {
      "os": "A",
      "status": 0
    }
  }
}
```

Backend consumers should interpret `status = 0` as “disconnect”. The app updates the same topic with other status codes when connecting.

### Disconnect Notifications

`evt/+/mobile/event/disconnect-mqtt` is broadcast by the cloud when the device-side MQTT client disconnects unexpectedly. The app treats receipt of this topic as a reason to refresh credentials.

### Control Failures

`ControlFailData` payloads describe rejection scenarios such as invalid parameters, busy devices, or authorization failures. Use `failCode` to differentiate cases. The Android app maps `ControlFailEvent` to UI error dialogs.

---

## Revision History

- **v1.1** — Corrected state/flag values throughout document. Fixed POWER command (`state`: 1=ON, 2=OFF, not 0=OFF). Fixed ON_DEMAND command (`flag`: 1=ON, 2=OFF, 3=WARMUP, not 0/1/2). Added comprehensive [Common Enum Values](#common-enum-values) section documenting that Navien APIs consistently use 0=UNKNOWN, 1=ON, 2=OFF pattern.
- **v1.0** — Initial legacy protocol reference distilled from the Navilink Android client (`SendRequestData`, `KDEnum`, `KDResponse*` classes).


