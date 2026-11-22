# Firmware

Two Arduino/ESP32 sketches implement the reference system. They are written
against the standard ESP32 Arduino core (tested target: 2.0.x / 3.x) and use
only built-in libraries.

```
firmware/
├── common/            # shared packet format and compile-time config
│   ├── config.h
│   └── Packet.h
├── sensor/            # static field sensor node
│   ├── sensor.ino
│   ├── SensorQueue.h
│   └── SensorQueue.cpp
└── mule/              # mobile collector
    ├── mule.ino
    ├── BufferManager.h / .cpp
    ├── FlashStore.h / .cpp
    └── Handshake.h / .cpp
```

## Build with Arduino IDE

1. Install **Arduino IDE 2.x** and the **esp32** boards package via Boards
   Manager (`esp32:esp32`).
2. Copy `common/`, `sensor/`, and `mule/` so each `.ino` folder also contains a
   copy of the two common headers, or add `common/` as an include path in
   `platform.local.txt`.
3. Open `sensor/sensor.ino`, select **ESP32 Dev Module**, set the `SENSOR_ID`
   and `SENSOR_POLICY` macros, and upload.
4. Open `mule/mule.ino`, select **ESP32 Dev Module**, choose the eviction policy
   with `-DEVICTION_POLICY=BufferManager::Eviction::PADS`, and upload.
5. Open the serial monitor at 115200 baud. The mule prints `[STAT]` lines every
   10 s; the sensor prints its buffering policy at boot.

## Build with PlatformIO (alternative)

```ini
[env:mule]
platform = espressif32
board = esp32dev
framework = arduino
build_flags = -DEVICTION_POLICY=BufferManager::Eviction::PADS

[env:sensor]
platform = espressif32
board = esp32dev
framework = arduino
```

## Compile-time policy selection

| Sketch | Macro | Values |
|--------|-------|--------|
| sensor | `SENSOR_POLICY` | `FIFO`, `SP`, `SP_EDF` (default), `SP_AGE` |
| mule | `EVICTION_POLICY` | `BufferManager::Eviction::{DROP_TAIL,DROP_OLDEST,DROP_LOWEST,PADS}` |

## Notes on validation

The firmware is compile-ready and fully commented, but this project had no
physical ESP32 boards available. Correctness of the *policies* was therefore
validated with the host-side simulator in `simulator/`, which uses the same
score functions and constants. See `docs/06_analysis.md` for the explicit
limitation and the proposed hardware-in-the-loop follow-up.
