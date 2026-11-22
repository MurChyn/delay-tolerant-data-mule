/**
 * @file config.h
 * @brief Shared compile-time configuration for the DTN data mule system.
 *
 * All values here are used by both the sensor and mule sketches. Changing the
 * packet size or capacity requires regenerating the simulator's matching
 * constants in simulator/dtn_sim.py.
 */
#pragma once

#include <stdint.h>

// ---------------------------------------------------------------------------
// Identity / network
// ---------------------------------------------------------------------------
#define MULE_SSID_PREFIX      "DTN-MULE-"
#define MULE_WIFI_CHANNEL     6
#define MULE_PASSWORD         "dtnmule123"      // WPA2, min 8 chars
#define UDP_PORT              5005
#define BASE_PORT             5006
#define MULE_IP_ADDRESS       {192, 168, 4, 1}
#define SENSOR_IP_BASE        10                // 192.168.4.(10 + id)

// ---------------------------------------------------------------------------
// Packet layout
// ---------------------------------------------------------------------------
#define PACKET_MAGIC          0x4D55            // "MU"
#define PACKET_VERSION        1
#define PAYLOAD_MAX           64                // bytes
#define PACKET_HEADER_SIZE    20                // bytes, see docs/03_protocol.md
#define PACKET_MAX_SIZE       (PACKET_HEADER_SIZE + PAYLOAD_MAX)
#define FLASH_RECORD_SIZE     128               // fixed-size storage record

// Message types
#define MSG_HELLO             1
#define MSG_SUMMARY           2
#define MSG_REQ               3
#define MSG_DATA              4
#define MSG_ACK               5
#define MSG_DONE              6

// Priority classes
#define PRIO_LOW              0
#define PRIO_HIGH             1

// ---------------------------------------------------------------------------
// Buffer sizing
// ---------------------------------------------------------------------------
#define SENSOR_QUEUE_CAPACITY 128               // packets (~16 KiB)
#define MULE_FLASH_RECORDS    4096               // records (~512 KiB)
#define SUMMARY_MAX_ENTRIES   64                 // seq numbers per SUMMARY

// ---------------------------------------------------------------------------
// Policy tuning
// ---------------------------------------------------------------------------
// Aging constant in seconds. A low-priority packet's effective score grows as
// (age / PRIO_AGING_TAU), so after PRIO_AGING_TAU seconds it is treated as
// comparable to one high-priority packet. Selected by simulation sweep.
#define PRIO_AGING_TAU        120

// Time-to-live defaults, seconds. High-priority readings are time-critical.
#define TTL_HIGH_DEFAULT      300
#define TTL_LOW_DEFAULT       3600

// Mule flash guard band: number of slots reserved for high-priority arrivals.
#define HP_GUARD_SLOTS        256

// Expected interval between base-station unloads. PADS refuses to store a
// record whose TTL will elapse before the next unload, because it could never
// be delivered and would waste a slot.
#define UNLOAD_INTERVAL_SEC   300

// Contact quality threshold (dBm) below which only high priority is requested.
#define RSSI_DEGRADED_LEVEL   -75

// ---------------------------------------------------------------------------
// Hardware pins (ESP32 DevKit V1)
// ---------------------------------------------------------------------------
#define PIN_STATUS_LED        2                 // onboard LED
#define PIN_BATTERY_ADC       34                 // optional battery monitor
#define PIN_SD_CS             5                  // optional SD card
#define PIN_SD_MOSI           23
#define PIN_SD_MISO           19
#define PIN_SD_SCK            18

// ---------------------------------------------------------------------------
// Debug
// ---------------------------------------------------------------------------
#define SERIAL_BAUD           115200
#define DEBUG_RADIO           0
