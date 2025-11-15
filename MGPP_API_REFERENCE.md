# MGPP Protocol API Reference

## Overview

The MGPP (Navien Water Heater) protocol is an MQTT-based communication protocol for controlling and monitoring Navien water heaters. This document describes the endpoints, message formats, and command structures used in the protocol.

## Table of Contents

1. [MQTT Topics and Endpoints](#mqtt-topics-and-endpoints)
2. [Message Format](#message-format)
3. [Request Structure](#request-structure)
4. [Response Structure](#response-structure)
5. [Command Messages](#command-messages)
6. [Response Fields](#response-fields)
7. [Event Messages](#event-messages)
8. [Installer Diagnostics](#installer-diagnostics)
9. [Temperature Encoding](#temperature-encoding)
10. [Notes](#notes)
11. [Revision History](#revision-history)

---

## MQTT Topics and Endpoints

### Topic Structure

MGPP uses MQTT topics with the following patterns:

#### Publish Topics (Commands)

1. **Status/Information Requests:**
   - Format: `cmd/{deviceType}/navilink-{macAddress}/{endpoint}`
   - Examples:
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st/did` - Device Information
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st` - Status
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st/td/rd` - Trend Data
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st/rsv/rd` - Reservation Status
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st/dl-sw-info` - Download Software Info
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st/energy-usage-daily-query/rd` - Daily Energy Usage Query
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st/energy-usage-monthly-query/rd` - Monthly Energy Usage Query
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/st/recirc-rsv/rd` - Recirculation Reservation Status

2. **Control Commands:**
   - Format: `cmd/{deviceType}/navilink-{macAddress}/ctrl/{command}`
   - Examples:
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/ctrl/rsv/rd` - Weekly Reservation Control
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/ctrl/recirc-rsv/rd` - Recirculation Reservation Control
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/ctrl/tou/rd` - Time-of-Use Reservation Control
     - `cmd/52/navilink-AA:BB:CC:DD:EE:FF/ctrl/commit-ota` - OTA Commit

#### Subscribe Topics (Responses)

1. **Default Response:**
   - Format: `cmd/{deviceType}/navilink-{macAddress}/res`

2. **Specific Response Endpoints:**
   - Format: `cmd/{deviceType}/{homeSeq}/{userSeq}/{clientId}/{endpoint}`
   - Examples:
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/did` - Device Information Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res` - General Status Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/rsv/rd` - Reservation Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/recirc-rsv/rd` - Recirculation Reservation Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/td/rd` - Trend Data Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/energy-usage-daily-query/rd` - Daily Energy Usage Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/energy-usage-monthly-query/rd` - Monthly Energy Usage Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/tou/rd` - Time-of-Use Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/dl-sw-info` - Download Software Info Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/end` - End Response
     - `cmd/52/{homeSeq}/{userSeq}/{clientId}/res/commit-ota` - OTA Commit Response
3. **Event Topics:**
   - `cmd/{deviceType}/navilink-{macAddress}/ctrl-fail` - Control failure notifications for rejected commands.
   - `evt/{deviceType}/navilink-{macAddress}/app-connection` - App-side connection heartbeat (`status <= 0` indicates disconnect).
   - `evt/{deviceType}/navilink-{macAddress}/connection` - Device heartbeat events (legacy fallback, handled alongside app connection updates).
   - `evt/+/mobile/event/disconnect-mqtt` - Backend broadcast when the device’s MQTT session drops.

### Endpoint Mappings

| Request Endpoint | Response Endpoint | Command ID | Description |
|-----------------|-------------------|------------|-------------|
| `st/did` | `res/did` | 0x1000001 (16777217) | Device Information |
| `st/end` | `res/end` | 0x1000002 (16777218) | End |
| `st` | `res` | 0x1000003 (16777219) | Status |
| `st/rsv/rd` | `res/rsv/rd` | 0x1000006 (16777222) | Reservation Status |
| `st/energy-usage-daily-query/rd` | `res/energy-usage-daily-query/rd` | 0x1000009 (16777225) | Daily Energy Usage Query |
| `st/energy-usage-monthly-query/rd` | `res/energy-usage-monthly-query/rd` | 0x100000a (16777226) | Monthly Energy Usage Query |
| `ctrl/rsv/rd` | `res/rsv/rd` | 16777226 | Weekly Reservation Control (Note: Same ID as monthly query, context-dependent) |
| `ctrl/recirc-rsv/rd` | `res/recirc-rsv/rd` | 33554440 | Recirculation Reservation Control |
| `ctrl/tou/rd` | `res/tou/rd` | 33554439 | Time-of-Use Reservation Control |
| `st/dl-sw-info` | `res/dl-sw-info` | 0x100000b (16777227) | Download Software Info |
| `st/td/rd` | `res/td/rd` | 0x100000c (16777228) | Trend Data |
| `st/recirc-rsv/rd` | `res/recirc-rsv/rd` | 0x100000f (16777231) | Recirculation Reservation Status |

---

## Message Format

### PublishMessage Structure

All MGPP messages are wrapped in a `PublishMessage` structure:

```json
{
  "protocolVersion": 2,
  "clientID": "string",
  "sessionID": "string (timestamp)",
  "requestTopic": "string",
  "responseTopic": "string",
  "request": {
    // Request-specific payload
  }
}
```

**Fields:**
- `protocolVersion`: Integer (always 2)
- `clientID`: String - Client identifier
- `sessionID`: String - Session identifier (typically timestamp in milliseconds)
- `requestTopic`: String - MQTT topic to publish the request to
- `responseTopic`: String - MQTT topic to subscribe to for the response
- `request`: Object - Request payload (varies by command type)

---

## Request Structure

### Base Request Fields

All requests include these common fields:

- `command`: Integer - Command ID (see Command IDs table)
- `deviceType`: Integer - Device type (e.g., 52 for MGPP devices)
- `macAddress`: String - Device MAC address (format: "AA:BB:CC:DD:EE:FF")
- `additionalValue`: String - Additional device identifier/value

### Request Types

#### 1. Device Information Request (`st/did`)

```json
{
  "command": 16777217,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string"
}
```

#### 2. Status Request (`st`)

```json
{
  "command": 16777219,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string"
}
```

#### 3. Control Request (`RequestMgppControl`)

Used for device control commands:

```json
{
  "command": 33554433-33554476,  // See DeviceControlMGPP enum
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string",
  "mode": "string",  // Command mode (e.g., "power-off", "dhw-mode", "dhw-temperature")
  "param": [int],    // Array of integer parameters
  "paramStr": ""     // String parameter (usually empty)
}
```

#### 4. Weekly Reservation Request (`RequestMgppWeekly`)

For regular weekly reservations:
```json
{
  "command": 16777226,  // Note: This is 0x100000a, same as monthly energy query command ID
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string",
  "reservationUse": 0|1|2,  // 0=UNKNOWN, 1=OFF, 2=ON
  "reservation": [
    {
      "enable": int,     // 1=disabled, 2=enabled
      "week": int,       // Bitmask: 128=Sun, 64=Mon, 32=Tue, 16=Wed, 8=Thu, 4=Fri, 2=Sat
      "hour": int,       // Hour (0-23)
      "min": int,        // Minute (0-59)
      "mode": int,       // Mode ID (see MgppReservationMode)
      "param": int       // Temperature parameter (encoded)
    }
  ]
}
```

For recirculation weekly reservations:
```json
{
  "command": 33554440,  // RECIR_RESERVATION from DeviceControlMGPP enum
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string",
  "reservationUse": 0|1|2,  // 0=UNKNOWN, 1=OFF, 2=ON
  "reservation": [
    {
      "enable": int,
      "week": int,
      "hour": int,
      "min": int,
      "mode": int,       // For recirculation: 1=OFF, 2=ON
      "param": int
    }
  ]
}
```

#### 5. Energy Usage Daily Query (`RequestMgppEmsDaily`)

```json
{
  "command": 16777225,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string",
  "year": int,      // Year (e.g., 2024)
  "month": [int]    // Array with single month (1-12, Calendar month)
}
```

#### 6. Energy Usage Monthly Query (`RequestMgppEmsMonthly`)

```json
{
  "command": 16777226,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string",
  "year": [int, int]  // Array: [year-1, year] (Calendar year)
}
```

#### 7. TOU Reservation Request (`RequestControlTou`)

```json
{
  "command": 33554439,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string",
  "controllerSerialNumber": "string",
  "reservationUse": int,  // 0=UNKNOWN, 1=OFF, 2=ON
  "reservation": [
    {
      // TouInterval structure
      "startHour": int,
      "startMin": int,
      "endHour": int,
      "endMin": int,
      "week": int,           // Bitmask (same as MgppReservationWeek)
      "season": long,        // Season identifier
      "decimalPoint": int,
      "priceMax": int,
      "priceMin": int
    }
  ]
}
```

#### 8. OTA Commit Request (`RequestControlOta`)

```json
{
  "command": 33554442,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string",
  "commitOta": {
    "swCode": int,      // or long
    "swVersion": int    // or long
  }
}
```

---

## Response Structure

### Base Response Format

All responses follow this structure:

```json
{
  "response": {
    // Response-specific data
  }
}
```

### Response Types

#### 1. Device Information Response (`KDResponseMgppDid`)

```json
{
  "response": {
    "feature": {
      "dhwUse": int,
      "dhwRefillUse": int,
      "temperatureType": int,  // 0=UNKNOWN, 1=CELSIUS, 2=FAHRENHEIT
      "smartDiagnosticUse": int,
      "panelSwCode": int,
      "highDemandUse": int,
      "dhwTemperatureSettingUse": int,  // 0=UNKNOWN, 1=DISABLED, 2=ENABLE_0_5_DEGREE, 3=ENABLE_1_DEGREE, 4=ENABLE_3_STAGE
      "volumeCode": int,
      "freezeProtectionUse": int,
      "hpwhUse": int,
      "wifiRssiUse": int,
      "wifiSwCode": int,
      "modelTypeCode": int,
      "controllerSwVersion": int,
      "drSettingUse": int,
      "antiLegionellaSettingUse": int,
      "countryCode": int,
      "dhwTemperatureMax": int,
      "freezeProtectionTempMax": int,
      "mixingValueUse": int,
      "tempFormulaType": int,
      "heatpumpUse": int,
      "energySaverUse": int,
      "controlTypeCode": int,
      "dhwTemperatureMin": int,
      "holidayUse": int,
      "controllerSwCode": int,
      "powerUse": int,
      "electricUse": int,
      "panelSwVersion": int,
      "wifiSwVersion": int,
      "programReservationUse": int,
      "freezeProtectionTempMin": int,
      "ecoUse": int,
      "controllerSerialNumber": "string",
      "energyUsageUse": int,
      "recirculationUse": int,
      "recircReservationUse": int,
      "recircTemperatureMin": int,
      "recircTemperatureMax": int,
      "title24Use": int,
      "recircSwVersion": int,
      "recircModelTypeCode": int
    }
  }
}
```

#### 2. Status Response (`KDResponseMgppStatus`)

```json
{
  "response": {
    "status": {
      "dhwUse": int,
      "temperatureType": int,  // 0=UNKNOWN, 1=CELSIUS, 2=FAHRENHEIT (display preference)
      "dhwOperationBusy": int,
      "dhwTemperature": int,
      "dhwTemperatureSetting": int,
      "dhwUseSustained": int,
      "errorCode": int,
      "heatUpperUse": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "heatLowerUse": int,
      "currentStatenum": int,
      "vacationDayElapsed": int,
      "freezeProtectionTemperature": int,
      "tankUpperTemperature": int,
      "specialFunctionStatus": int,
      "shutOffValveUse": int,
      "currentHeatUse": int,  // Heat source enum
      "currentSuperHeat": int,
      "eevStep": int,
      "wifiRssi": int,
      "smartDiagnostic": int,
      "conOvrSensorUse": int,
      "targetSuperHeat": int,
      "scaldUse": int,
      "fanPwm": int,
      "drEventStatus": int,
      "currentDhwFlowRate": int,
      "dischargeTemperature": int,
      "programReservationUse": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "ecoUse": int,
      "antiLegionellaPeriod": int,
      "programReservationType": int,
      "tankLowerTemperature": int,
      "dhwTemperature2": int,
      "dhwOperationSetting": int,  // MgppOperationMode enum
      "currentInletTemperature": int,
      "targetFanRpm": int,
      "currentInstPower": int,
      "subErrorCode": int,
      "freezeProtectionUse": int,
      "currentFanRpm": int,
      "didReload": int,
      "eevUse": int,
      "evaporatorTemperature": int,
      "outsideTemperature": int,
      "operationMode": int,  // MgppOperationMode enum
      "dhwTargetTemperatureSetting": int,
      "wtrOvrSensorUse": int,
      "compUse": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "mixingRate": int,
      "cumulatedOpTimeEvaFan": int,
      "drOverrideStatus": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "touStatus": int,
      "touOverrideStatus": int,
      "tempFormulaType": int,
      "dhwChargePer": int,
      "suctionTemperature": int,
      "command": int,
      "ambientTemperature": int,
      "airFilterAlarmUse": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "airFilterAlarmPeriod": int,
      "airFilterAlarmElapsed": int,
      "faultStatus1": int,
      "faultStatus2": int,
      "operationBusy": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "errorBuzzerUse": int,
      "vacationDaySetting": int,
      "antiLegionellaUse": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "antiLegionellaOperationBusy": int,  // 0=UNKNOWN, 1=OFF, 2=ON
      "recircOperationBusy": int,
      "recircReservationUse": int,
      "recircOperationMode": int,
      "recircTempSetting": int,
      "recircTemperature": int,
      "recircPumpOperationStatus": int,
      "recircFaucetTemperature": int,
      "recircHotBtnReady": int,
      "recircOperationReason": int,
      "recircDhwFlowRate": int,
      "recircErrorStatus": int
    }
  }
}
```

**Temperature Encoding Notes:**
- `ambientTemperature`, `currentSuperHeat`, `dischargeTemperature`, `evaporatorTemperature`, `suctionTemperature`, `tankLowerTemperature`, `tankUpperTemperature`: Divide by 5 to get actual temperature
- `dhwTemperature`, `dhwTemperatureSetting`: Raw value (for Celsius: divide by 2; for Fahrenheit: use conversion formula)

#### 3. Reservation Response (`KDResponseMgppRsv`)

```json
{
  "response": {
    "reservationUse": int,  // 0=UNKNOWN, 1=OFF, 2=ON
    "reservation": [
      {
        "enable": int,   // 1=disabled, 2=enabled
        "week": int,     // Bitmask for days of week
        "hour": int,     // Hour (0-23)
        "min": int,      // Minute (0-59)
        "mode": int,     // Mode ID
        "param": int     // Temperature parameter
      }
    ]
  }
}
```

#### 4. Trend Data Response (`KDResponseMgppTd`)

```json
{
  "response": {
    "data": {
      "tdData": {
        "dhwUseTotalFlow": int,
        "avrageRecoveryTime": int,
        "longDhwUseTotalTime": int,
        "numOfShortDhwUse": int,
        "numOfdhwUse": int,
        "numOfLongDhwUse": int,
        "longDhwUseTotalFlow": int,
        "dhwUseTotalTime": int
      },
      "tsData": {
        "cumulatedOccNumAbDisSucTmp": int,
        "cumulatedOpTimeDrShed": int,
        "cumulatedOccNumHpo": int,
        "cumulatedOpTimeDrAdvLoadUp": int,
        "cumulatedOccNumAbDisTmp": int,
        "cumulatedOpTimeDrCpp": int,
        "cumulatedPwrHp": int,
        "numOffRostProtectBurn": int,
        "cumulatedOpTimeDrGridEmg": int,
        "cumulatedOccNumDryFire": int,
        "cumulatedOpTimeDrLoadUp": int,
        "cumulatedOccNumWtrOvrFlow": int,
        "cumulatedOccNumAbSucTmp": int,
        "daysSinceInstallation": int,
        "cumulatedOccNumEco": int,
        "cumulatedOccNumConOvrFlow": int,
        "cumulatedPwrHe": int
      },
      "taData": {
        "mixingValveOpAvgMixinGrate": int,
        "cumulatedOpNumEvaFan": int,
        "cumulatedOpNumUhe": int,
        "mixingValveOpTotalStep": int,
        "cumulatedOpStepEev": int,
        "cumulatedOpTimeUhe": int,
        "cumulatedOpNumLhe": int,
        "cumulatedOpTimeLhe": int,
        "cumulatedOpNumShutOffVv": int,
        "cumulatedOpTimeComp": int,
        "cumulatedOpNumComp": int,
        "cumulatedOpTimeEvaFan": int
      }
    }
  }
}
```

#### 5. Energy Usage Response (`KDResponseMgppEnergyUsage`)

```json
{
  "response": {
    "typeOfUsage": int,  // 0=daily, 1=monthly
    "total": {
      "heUsage": int,    // Electric heater usage
      "hpUsage": int,    // Heat pump usage
      "heTime": int,     // Electric heater time
      "hpTime": int      // Heat pump time
    },
    "usage": [
      {
        "year": int,
        "month": int,
        "day": int,
        "data": [
          {
            "heUsage": int,
            "hpUsage": int,
            "heTime": int,
            "hpTime": int
          }
        ]
      }
    ]
  }
}
```

#### 6. Download Software Info Response (`KDResponseMgppDlSWInfo`)

```json
{
  "response": {
    "deviceType": int,
    "macAddress": "string",
    "additionalValue": "string",
    "downloadSwInfo": [
      {
        "swCode": int,
        "otaMode": int,
        "swVersion": int,
        "status": int
      }
    ]
  }
}
```

---

## Command Messages

### Device Control Commands

All control commands use the `RequestMgppControl` structure with different `mode` and `param` values.

#### Command IDs (DeviceControlMGPP)

| Command | ID | Mode | Parameters | Description |
|---------|-----|------|------------|-------------|
| POWER_OFF | 33554433 | "power-off" | `[]` | Turn device off |
| POWER_ON | 33554434 | "power-on" | `[]` | Turn device on |
| DHW_OPERATION_MODE | 33554437 | "dhw-mode" | `[mode]` or `[mode, days]` | Set operation mode (if VACATION mode, include days) |
| RESERVATION_WEEKLY | 33554438 | N/A | `RequestMgppWeekly` payload | Weekly reservation control (see RequestMgppWeekly) |
| TOU_RESERVATION | 33554439 | N/A | `RequestControlTou` payload | Time-of-use reservation control (TouInterval list) |
| RECIR_RESERVATION | 33554440 | N/A | `RequestMgppWeekly` payload | Recirculation weekly reservation control |
| RESERVATION_WATER_PROGRAM | 33554441 | "reservation-mode" | `[]` | Set reservation water program |
| OTA_COMMIT | 33554442 | N/A | `swCode`, `swVersion` | OTA commit (uses RequestControlOta) |
| OTA_CHECK | 33554443 | N/A | `[]` | OTA availability check (defined, not used in current app) |
| RECIR_HOT_BTN | 33554444 | "recirc-hotbtn" | `[state]` | Trigger recirculation hot button |
| RECIR_MODE | 33554445 | "recirc-mode" | `[mode]` | Set recirculation mode |
| WIFI_RECONNECT | 33554446 | N/A | `[]` | Wi-Fi reconnect (enum defined, no handler in current app) |
| WIFI_RESET | 33554447 | N/A | `[]` | Wi-Fi reset (enum defined, no handler in current app) |
| FREZ_TEMP | 33554451 | N/A | `[]` | Freeze temperature command (enum defined, no handler in current app) |
| SMART_DIAGNOSTIC | 33554455 | N/A | `[]` | Smart diagnostic command (enum defined, no handler in current app) |
| DHW_TEMPERATURE | 33554464 | "dhw-temperature" | `[temp]` | Set DHW temperature (encoded: Celsius*2 or Fahrenheit formula) |
| GOOUT_DAY | 33554466 | "goout-day" | `[days]` | Set vacation/away days |
| RESERVATION_INTELLIGENT_OFF | 33554467 | "intelligent-off" | `[]` | Disable intelligent reservation |
| RESERVATION_INTELLIGENT_ON | 33554468 | "intelligent-on" | `[]` | Enable intelligent reservation |
| DR_OFF | 33554469 | "dr-off" | `[]` | Disable demand response |
| DR_ON | 33554470 | "dr-on" | `[]` | Enable demand response |
| ANTI_LEGIONELLA_OFF | 33554471 | "anti-leg-off" | `[]` | Disable anti-legionella |
| ANTI_LEGIONELLA_ON | 33554472 | "anti-leg-on" | `[period]` | Enable anti-legionella with period |
| AIR_FILTER_RESET | 33554473 | "air-filter-reset" | `[]` | Reset air filter timer |
| AIR_FILTER_LIFE | 33554474 | "air-filter-life" | `[life]` | Set air filter life (in hours/500) |
| TOU_OFF | 33554475 | "tou-off" | `[]` | Disable time-of-use |
| TOU_ON | 33554476 | "tou-on" | `[]` | Enable time-of-use |

### Operation Modes (MgppOperationMode)

| Mode | ID | Description |
|------|-----|-------------|
| STANDBY | 0 | Standby mode |
| HEATPUMP | 1 | Heat pump mode |
| ELECTRIC | 2 | Electric mode |
| ENERGYSAVER | 3 | Energy saver mode |
| HIGHDEMAND | 4 | High demand mode |
| VACATION | 5 | Vacation mode (requires days parameter) |
| POWER_OFF | 6 | Power off |

### Reservation Modes (MgppReservationMode)

| Mode | ID | Description |
|------|-----|-------------|
| NOT_RESERVATION | 0 | Not a reservation |
| HEATPUMP | 1 | Heat pump mode |
| ELECTRIC | 2 | Electric mode |
| ENERGYSAVER | 3 | Energy saver mode |
| HIGHDEMAND | 4 | High demand mode |
| POWER_OFF | 5 | Power off |

### Reservation Week Days (MgppReservationWeek)

Days are combined using bitwise OR:

| Day | ID | Bit Value |
|-----|-----|-----------|
| SUN | 128 | 0x80 |
| MON | 64 | 0x40 |
| TUE | 32 | 0x20 |
| WED | 16 | 0x10 |
| THU | 8 | 0x08 |
| FRI | 4 | 0x04 |
| SAT | 2 | 0x02 |

Example: Monday, Wednesday, Friday = 64 | 16 | 4 = 84

### On/Off Flags (MgppOnOFFFlag)

| Value | ID | Description |
|-------|-----|-------------|
| UNKNOWN | 0 | Unknown state |
| OFF | 1 | Off |
| ON | 2 | On |

---

## Command Examples

### Setting Temperature

**Celsius:**
- Temperature value = desired_temp * 2
- Example: 50°C → `param: [100]`

**Fahrenheit:**
- Temperature value = conversion formula based on `tempFormulaType`
- Formula type determines conversion method

### Setting Operation Mode

```json
{
  "command": 33554437,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "",
  "mode": "dhw-mode",
  "param": [1],  // 1 = HEATPUMP
  "paramStr": ""
}
```

### Vacation Mode (with days)

```json
{
  "command": 33554437,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "",
  "mode": "dhw-mode",
  "param": [5, 7],  // 5 = VACATION, 7 = days
  "paramStr": ""
}
```

### Setting Weekly Reservation

```json
{
  "command": 16777226,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "",
  "reservationUse": 1,  // 1 = ON
  "reservation": [
    {
      "enable": 2,      // 2 = enabled
      "week": 84,       // Mon, Wed, Fri (64+16+4)
      "hour": 6,        // 6 AM
      "min": 30,        // 30 minutes
      "mode": 1,        // HEATPUMP
      "param": 100      // 50°C (100/2)
    }
  ]
}
```

### Setting Anti-Legionella

```json
{
  "command": 33554472,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "",
  "mode": "anti-leg-on",
  "param": [7],  // Period in days
  "paramStr": ""
}
```

---

## Response Fields

### Device Information (Feature) Fields

| Field | Type | Description |
|-------|------|-------------|
| `dhwUse` | int | DHW (Domestic Hot Water) use flag |
| `dhwRefillUse` | int | DHW refill use flag |
| `temperatureType` | int | 0=Unknown, 1=Celsius UI mode, 2=Fahrenheit UI mode |
| `smartDiagnosticUse` | int | Smart diagnostic feature availability |
| `panelSwCode` | int | Panel software code |
| `highDemandUse` | int | High demand mode availability |
| `dhwTemperatureSettingUse` | int | Temperature setting granularity (0=Unknown, 1=Disabled, 2=0.5°C increments, 3=1°C increments, 4=3-stage) |
| `volumeCode` | int | Tank volume code |
| `freezeProtectionUse` | int | Freeze protection availability |
| `hpwhUse` | int | Heat pump water heater use flag |
| `wifiRssiUse` | int | WiFi RSSI reporting availability |
| `wifiSwCode` | int | WiFi software code |
| `modelTypeCode` | int | Model type code |
| `controllerSwVersion` | int | Controller software version |
| `drSettingUse` | int | Demand response setting availability |
| `antiLegionellaSettingUse` | int | Anti-legionella setting availability |
| `countryCode` | int | Country code |
| `dhwTemperatureMax` | int | Maximum DHW temperature (encoded) |
| `dhwTemperatureMin` | int | Minimum DHW temperature (encoded) |
| `freezeProtectionTempMax` | int | Maximum freeze protection temperature |
| `freezeProtectionTempMin` | int | Minimum freeze protection temperature |
| `tempFormulaType` | int | Temperature conversion formula type |
| `heatpumpUse` | int | Heat pump availability |
| `energySaverUse` | int | Energy saver mode availability |
| `electricUse` | int | Electric mode availability |
| `controllerSwCode` | int | Controller software code |
| `powerUse` | int | Power control availability |
| `panelSwVersion` | int | Panel software version |
| `wifiSwVersion` | int | WiFi software version |
| `programReservationUse` | int | Program reservation availability |
| `ecoUse` | int | ECO mode availability |
| `controllerSerialNumber` | string | Controller serial number |
| `energyUsageUse` | int | Energy usage reporting availability |
| `recirculationUse` | int | Recirculation feature availability |
| `recircReservationUse` | int | Recirculation reservation availability |
| `recircTemperatureMin` | int | Minimum recirculation temperature (encoded) |
| `recircTemperatureMax` | int | Maximum recirculation temperature (encoded) |
| `title24Use` | int | Title 24 compliance availability |
| `recircSwVersion` | int | Recirculation software version |
| `recircModelTypeCode` | int | Recirculation model type code |

### Status Fields

| Field | Type | Description | Notes |
|-------|------|-------------|-------|
| `dhwUse` | int | DHW use status | |
| `temperatureType` | int | Temperature display mode | 0=Unknown, 1=Celsius UI mode, 2=Fahrenheit UI mode |
| `dhwOperationBusy` | int | DHW operation busy status | |
| `dhwTemperature` | int | Current DHW temperature | Raw value (decode based on temperatureType) |
| `dhwTemperatureSetting` | int | Set DHW temperature | Raw value (decode based on temperatureType) |
| `dhwUseSustained` | int | Sustained DHW use | |
| `errorCode` | int | Error code | 0 = no error |
| `subErrorCode` | int | Sub error code | |
| `heatUpperUse` | int | Upper heater status | 0=UNKNOWN, 1=OFF, 2=ON |
| `heatLowerUse` | int | Lower heater status | 0=UNKNOWN, 1=OFF, 2=ON |
| `currentStatenum` | int | Current state number | |
| `vacationDayElapsed` | int | Vacation days elapsed | |
| `vacationDaySetting` | int | Vacation days setting | |
| `freezeProtectionTemperature` | int | Freeze protection temperature | |
| `freezeProtectionUse` | int | Freeze protection status | |
| `tankUpperTemperature` | int | Upper tank temperature | Divide by 5 |
| `tankLowerTemperature` | int | Lower tank temperature | Divide by 5 |
| `specialFunctionStatus` | int | Special function status | |
| `shutOffValveUse` | int | Shut-off valve status | |
| `currentHeatUse` | int | Current heat source | Enum value |
| `currentSuperHeat` | int | Current superheat | Divide by 5 |
| `targetSuperHeat` | int | Target superheat | |
| `eevStep` | int | Electronic expansion valve step | |
| `eevUse` | int | EEV use status | |
| `wifiRssi` | int | WiFi signal strength | |
| `smartDiagnostic` | int | Smart diagnostic status | |
| `conOvrSensorUse` | int | Condenser override sensor use | |
| `scaldUse` | int | Scald protection status | |
| `fanPwm` | int | Fan PWM value | |
| `currentFanRpm` | int | Current fan RPM | |
| `targetFanRpm` | int | Target fan RPM | |
| `drEventStatus` | int | Demand response event status | Enum value |
| `drOverrideStatus` | int | DR override status | 0=UNKNOWN, 1=OFF, 2=ON |
| `currentDhwFlowRate` | int | Current DHW flow rate | |
| `dischargeTemperature` | int | Discharge temperature | Divide by 5 |
| `suctionTemperature` | int | Suction temperature | Divide by 5 |
| `evaporatorTemperature` | int | Evaporator temperature | Divide by 5 |
| `ambientTemperature` | int | Ambient temperature | Divide by 5 |
| `currentInletTemperature` | int | Current inlet temperature | |
| `currentInstPower` | int | Current instantaneous power | |
| `programReservationUse` | int | Program reservation status | 0=UNKNOWN, 1=OFF, 2=ON |
| `programReservationType` | int | Program reservation type | |
| `ecoUse` | int | ECO mode status | |
| `antiLegionellaPeriod` | int | Anti-legionella period | |
| `antiLegionellaUse` | int | Anti-legionella status | 0=UNKNOWN, 1=OFF, 2=ON |
| `antiLegionellaOperationBusy` | int | Anti-legionella operation busy | 0=UNKNOWN, 1=OFF, 2=ON |
| `dhwTemperature2` | int | Secondary DHW temperature | |
| `dhwOperationSetting` | int | DHW operation setting mode | Enum: MgppOperationMode |
| `dhwTargetTemperatureSetting` | int | Target DHW temperature setting | |
| `operationMode` | int | Operation mode | Enum: MgppOperationMode |
| `wtrOvrSensorUse` | int | Water override sensor use | |
| `compUse` | int | Compressor use status | 0=UNKNOWN, 1=OFF, 2=ON |
| `mixingRate` | int | Mixing rate | |
| `cumulatedOpTimeEvaFan` | int | Cumulative operation time (evaporator fan) | |
| `touStatus` | int | Time-of-use status | |
| `touOverrideStatus` | int | TOU override status | |
| `tempFormulaType` | int | Temperature formula type | |
| `dhwChargePer` | int | DHW charge percentage | |
| `command` | int | Last command | |
| `airFilterAlarmUse` | int | Air filter alarm status | 0=UNKNOWN, 1=OFF, 2=ON |
| `airFilterAlarmPeriod` | int | Air filter alarm period | |
| `airFilterAlarmElapsed` | int | Air filter alarm elapsed time | |
| `faultStatus1` | int | Fault status 1 | |
| `faultStatus2` | int | Fault status 2 | |
| `operationBusy` | int | Operation busy status | 0=UNKNOWN, 1=OFF, 2=ON |
| `errorBuzzerUse` | int | Error buzzer status | |
| `didReload` | int | Device ID reload flag | |
| `recircOperationBusy` | int | Recirculation operation busy | |
| `recircReservationUse` | int | Recirculation reservation status | |
| `recircOperationMode` | int | Recirculation operation mode | Enum |
| `recircTempSetting` | int | Recirculation temperature setting | |
| `recircTemperature` | int | Recirculation temperature | |
| `recircPumpOperationStatus` | int | Recirculation pump operation status | |
| `recircFaucetTemperature` | int | Recirculation faucet temperature | |
| `recircHotBtnReady` | int | Recirculation hot button ready | |
| `recircOperationReason` | int | Recirculation operation reason | |
| `recircDhwFlowRate` | int | Recirculation DHW flow rate | |
| `recircErrorStatus` | int | Recirculation error status | |

### Reservation Fields

| Field | Type | Description |
|-------|------|-------------|
| `enable` | int | 1=disabled, 2=enabled |
| `week` | int | Bitmask for days of week (see MgppReservationWeek) |
| `hour` | int | Hour (0-23, 24-hour format) |
| `min` | int | Minute (0-59) |
| `mode` | int | Reservation mode ID (see MgppReservationMode) |
| `param` | int | Temperature parameter (encoded) |

### Energy Usage Fields

| Field | Type | Description |
|-------|------|-------------|
| `typeOfUsage` | int | 0=daily, 1=monthly |
| `total.heUsage` | int | Total electric heater energy usage |
| `total.hpUsage` | int | Total heat pump energy usage |
| `total.heTime` | int | Total electric heater operation time |
| `total.hpTime` | int | Total heat pump operation time |
| `usage[].year` | int | Year |
| `usage[].month` | int | Month (1-12) |
| `usage[].day` | int | Day (1-31) |
| `usage[].data[].heUsage` | int | Electric heater usage for period |
| `usage[].data[].hpUsage` | int | Heat pump usage for period |
| `usage[].data[].heTime` | int | Electric heater time for period |
| `usage[].data[].hpTime` | int | Heat pump time for period |

---

## Event Messages

### Control Failure Notifications (`cmd/{deviceType}/navilink-{macAddress}/ctrl-fail`)

When the platform rejects a control command it publishes a `ControlFailData` envelope on the device-scoped `ctrl-fail` topic. The message structure mirrors other MGPP envelopes and carries the original request topic plus a `ControlFailEvent` payload:

```json
{
  "protocolVersion": 2,
  "clientID": "string",
  "sessionID": "ms-since-epoch",
  "requestTopic": "cmd/{deviceType}/navilink-{macAddress}/ctrl/{command}",
  "response": {
    "deviceType": 52,
    "macAddress": "AA:BB:CC:DD:EE:FF",
    "additionalValue": "string",
    "swVersion": 0,
    "failCode": 2
  }
}
```

Client models confirm the schema used by these notifications:

```3:9:com/kdnavien/navilink/mqttData/ControlFailData.java
public class ControlFailData {
    public String clientID;
    public int protocolVersion;
    public String requestTopic;
    public ControlFailEvent response;
    public String sessionID;
}
```

```3:9:com/kdnavien/navilink/mqttData/ControlFailEvent.java
public class ControlFailEvent {
    public String additionalValue;
    public int deviceType;
    public int failCode;
    public String macAddress;
    public int swVersion;
}
```

Known `failCode` values:

- `2` — Control interval lockout; the handset renders “control interval exceeded” and leaves other codes to future expansion.

```1129:1133:com/kdnavien/navilink/fragment/MgppControlFragment.java
} else if (str.contains("ctrl-fail")) {
    if (((ControlFailData) new Gson().fromJson(str2, ControlFailData.class)).response.failCode == 2) {
        showControlIntervalError();
        return;
    }
```

### Connection Heartbeat (`evt/{deviceType}/navilink-{macAddress}/app-connection`)

The Android client registers an MQTT Last Will on `evt/{deviceType}/navilink-{macAddress}/app-connection`. When the app disconnects ungracefully the broker delivers the Last Will payload (`status = 0`) so other subscribers can react. While connected the app may publish updates with positive `status` values.

```731:745:com/kdnavien/navilink/NavilinkApplication.java
RequestLastWill requestLastWill = new RequestLastWill();
requestLastWill.sessionID = String.valueOf(System.currentTimeMillis());
requestLastWill.clientID = this.clientId;
requestLastWill.protocolVersion = 1;
requestLastWill.requestTopic = createRCConnectTopic("app-connection");
requestLastWill.event.macAddress = getDeviceInfoData().getMacAddress();
requestLastWill.event.additionalValue = getDeviceInfoData().getAdditionalValue();
requestLastWill.event.deviceType = this.deviceInfoData.getDeviceType();
RequestLastWillConnection requestLastWillConnection = requestLastWill.event.connection;
requestLastWillConnection.os = "A";
requestLastWillConnection.status = 0;
AWSIoTMqttHelper.getMqttManager().setMqttLastWillAndTestament(new AWSIotMqttLastWillAndTestament(createRCConnectTopic("app-connection"), new Gson().toJson((Object) requestLastWill), AWSIotMqttQos.QOS1));
```

Last Will / heartbeat payload:

```json
{
  "protocolVersion": 1,
  "clientID": "string",
  "sessionID": "ms-since-epoch",
  "requestTopic": "evt/{deviceType}/navilink-{macAddress}/app-connection",
  "event": {
    "deviceType": 52,
    "macAddress": "AA:BB:CC:DD:EE:FF",
    "additionalValue": "string",
    "connection": {
      "os": "A",
      "status": 0
    }
  }
}
```

The Last Will uses `RequestLastWillConnection`, while live updates arrive as `EventStatus` messages whose `Connection` objects also include the `sessionNumber` assigned by the broker. The client treats `status <= 0` as offline:

```3:8:com/kdnavien/navilink/mqttData/EventStatus.java
public class EventStatus {
    public String clientID;
    public ConnectEvent event;
    public int protocolVersion;
    public String requestTopic;
    public String sessionID;
}
```

```3:9:com/kdnavien/navilink/mqttData/ConnectEvent.java
public class ConnectEvent {
    public String additionalValue;
    public Connection connection;
    private int countryCode;
    public int deviceType;
    public String macAddress;
}
```

```3:5:com/kdnavien/navilink/mqttData/Connection.java
public class Connection {
    public int sessionNumber;
    public int status;
}
```

```1135:1145:com/kdnavien/navilink/fragment/MgppControlFragment.java
} else if (str.contains("/app-connection") && ((EventStatus) new Gson().fromJson(str2, EventStatus.class)).event.connection.status <= 0) {
    this.act.showPopupDialog(true, getString(R.string.notice), getString(R.string.popup_msg_disconnect_device), (PopupDialog.KDDialogInterface) new PopupDialog.KDDialogInterface() {
        public void onCancel() {
        }

        public void onConfirm() {
            if (MgppControlFragment.this.refreshDismissHandler != null) {
                MgppControlFragment.this.refreshDismissHandler.removeCallbacks(MgppControlFragment.this.refreshDismissRunnable);
            }
            MgppControlFragment.this.disconnectMqtt(false);
        }
    });
    return;
}
```

The UI also listens for `evt/{deviceType}/navilink-{macAddress}/connection` alongside `app-connection` for backward compatibility; both payloads reuse the same schema.

### Disconnect Broadcast (`evt/+/mobile/event/disconnect-mqtt`)

The backend emits `evt/+/mobile/event/disconnect-mqtt` when it detects a device-side MQTT drop. The client does not parse the payload; receipt alone triggers a toast and forces the user back to the device list.

```204:229:com/kdnavien/navilink/NavilinkApplication.java
public final void WIFIDataNew(String str, String str2) {
    KDEventListener kDEventListener;
    int i;
    if (str.contains("/controlfail")) {
        kDEventListener = this.callback;
        if (kDEventListener != null) {
            i = 4;
        } else {
            return;
        }
    } else if (str.contains("mobile/event/disconnect-mqtt")) {
        kDEventListener = this.callback;
        if (kDEventListener != null) {
            i = 5;
        } else {
            return;
        }
    } else {
        KDEventListener kDEventListener2 = this.callback;
        if (kDEventListener2 != null) {
            kDEventListener2.onDataChange(1, str, str2);
            return;
        }
        return;
    }
    kDEventListener.onDataChange(i, str, str2);
}
```

```446:465:com/kdnavien/navilink/activity/KDBaseActivity.java
public void onDataChange(int i, String str, String str2) {
    if (3 == i) {
        LogUtil.log("10 minute Time Out");
        if (!isFinishing() && !isDestroyed()) {
            runOnUiThread(new KDBaseActivity$$ExternalSyntheticLambda6(this));
        }
    } else if (4 == i) {
        LogUtil.log("에러 controlfail topic 수신시에 ");
        showPopupDialog(true, getString(R.string.notice), getString(R.string.string_error_occurred), (PopupDialog.KDDialogInterface) new PopupDialog.KDDialogInterface() {
            public void onCancel() {
            }

            public void onConfirm() {
            }
        });
    } else if (5 == i) {
        LogUtil.log("서버 점검중 ");
        showToast(getString(R.string.server_check));
        disConnectMQTTandMoveBack();
    } else {
        dataChange(i, str, str2);
    }
}
```

## Installer Diagnostics

Installer-role accounts (`userType = "I"`) automatically request the trend diagnostics bundle after every status refresh. The client publishes `st/td/rd` and expects a `KDResponseMgppTd` payload (documented in [Trend Data Response](#response-structure)).

```json
{
  "command": 16777228,
  "deviceType": 52,
  "macAddress": "AA:BB:CC:DD:EE:FF",
  "additionalValue": "string"
}
```

```1293:1295:com/kdnavien/navilink/fragment/MgppControlFragment.java
public final void requestInstallerData() {
    NavilinkApplication.getInstance().setPublishMgpp("st/td/rd", this.act.getDeviceInfoData().getDeviceType(), this.act.getDeviceInfoData().getMacAddress(), this.act.getDeviceInfoData().getAdditionalValue());
}
```

```576:580:com/kdnavien/navilink/fragment/MgppStatusFragment.java
if (TextUtils.isEmpty(this.act.getUserData().getUserType()) || !this.act.getUserData().getUserType().equals(DefineData.USER_TYPE_STRING_VALUE_INSTALLER)) {
    this.act.dismissLoadingDialog();
} else {
    requestInstallerData();
}
```

The resulting `Trend Data Response`’s `tdData`/`tsData`/`taData` collections feed the installer-only tabs (TDD/TDS/TAD) in the status UI. Non-installer accounts may issue the same request manually, but the stock app only performs it automatically for installer accounts.

---

## Temperature Encoding

MGPP exposes temperature values using two different encodings, depending on the field:

1. **Half-degree Celsius base (×0.5 °C increments)**  
   - Applies to control/setpoint-oriented values such as `dhwTemperature`, `dhwTemperatureSetting`, `dhwTargetTemperatureSetting`, weekly reservation `param`, recirculation setpoints, etc.  
   - **Encode**: multiply the desired Celsius temperature by 2, and round to the nearest integer value.
   - **Decode to Celsius**: convert to a floating point value and divide the raw value by 2.0.

2. **Tenth-degree Celsius base (×0.1 °C increments)**  
   - Applies to telemetry samples the app treats as sensor data, including `ambientTemperature`, `currentSuperHeat`, `dischargeTemperature`, `evaporatorTemperature`, `suctionTemperature`, `tankLowerTemperature`, and `tankUpperTemperature`. These values are divided by five in the data layer and again by two when rendered, i.e. the wire value is actual Celsius × 10.  
   - **Encode**: multiply the desired Celsius temperature by 10, and round to the nearest integer value.
   - **Decode to Celsius**: convert to a floating point value and divide the raw value by 10.0.

### Temperature Reading

For status responses:
- `dhwTemperature`, `dhwTemperatureSetting`, `dhwTargetTemperatureSetting`: Use the half-degree encoding (`raw / 2` for Celsius).
- `ambientTemperature`, `currentSuperHeat`, `dischargeTemperature`, `evaporatorTemperature`, `suctionTemperature`, `tankUpperTemperature`, `tankLowerTemperature`: Use the tenth-degree encoding (`raw / 10` for Celsius).

---

## Notes

1. **Protocol Version**: Always use protocol version 2
2. **Session ID**: Typically uses timestamp in milliseconds as string
3. **Temperature Units**: Use `temperatureType` for presentation, and apply the appropriate half-degree or tenth-degree decoding listed above before converting units.
4. **Week Day Encoding**: Days are combined using bitwise OR operation
5. **Mode Values**: Use enum IDs for operation modes and reservation modes
6. **Error Handling**: Check `errorCode` and `subErrorCode` in status responses
7. **Subscription**: Always subscribe to response topics before publishing requests
8. **Command Parameters**: Some commands require specific parameter formats (see command examples)

---

## Revision History

- **v1.0** - Initial API reference document based on Navilink Android application source code analysis

