/**
 * @file mule.ino
 * @brief ESP32 mobile data mule: collect, store, and unload field data.
 *
 * Compile-time modes
 * ------------------
 *  COLLECT_MODE (default) : soft-AP, receive data from passing sensors.
 *  BASE_STATION_MODE      : connect to infrastructure AP and upload flash.
 *
 * The mule never assumes an end-to-end path. It stores before acknowledging,
 * so a packet reported as delivered to a sensor is durable in flash.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <time.h>

#include "config.h"
#include "Packet.h"
#include "FlashStore.h"
#include "BufferManager.h"
#include "Handshake.h"

// ---- Select one mode -------------------------------------------------------
#define COLLECT_MODE 1
// #define BASE_STATION_MODE 1

#ifndef EVICTION_POLICY
#define EVICTION_POLICY BufferManager::Eviction::PADS
#endif

static FlashStore     flash;
static BufferManager  buffer(flash, EVICTION_POLICY);
static Handshake      handshake;
static WiFiUdp        udp;

static uint8_t        muleId = 0;
static uint32_t       ackSeqs[64];
static uint16_t       ackCount = 0;
static uint32_t       lastStatsMs = 0;
static uint32_t       accepted = 0;
static uint32_t       rejected = 0;

static uint32_t nowSec() {
    time_t t = time(nullptr);
    return (t > 1700000000L) ? (uint32_t)t : (millis() / 1000u);
}

static void sendTo(const IPAddress& ip, uint16_t port, const Packet& p) {
    udp.beginPacket(ip, port);
    udp.write((const uint8_t*)&p, PACKET_HEADER_SIZE + p.header.payloadLen);
    udp.endPacket();
}

static void sendAck(uint16_t sensorId) {
    Packet p;
    uint8_t payload[PAYLOAD_MAX];
    uint16_t n = ackCount;
    if (n > 12) n = 12;                 // 12 x uint32 = 48 bytes
    for (uint16_t i = 0; i < n; ++i) memcpy(payload + i * 4, &ackSeqs[i], 4);
    packetInit(p, MSG_ACK, muleId, 0, PRIO_LOW, nowSec(), 60, payload, n * 4);
    sendTo(udp.remoteIP(), UDP_PORT, p);
    ackCount = 0;
}

static void sendDone(uint16_t sensorId) {
    Packet p;
    uint8_t payload[8] = {0};
    uint16_t stored = flash.validCount();
    memcpy(payload, &stored, 2);
    payload[2] = (uint8_t)(accepted & 0xFF);
    packetInit(p, MSG_DONE, muleId, 0, PRIO_LOW, nowSec(), 60, payload, 6);
    sendTo(udp.remoteIP(), UDP_PORT, p);
}

/** Handle HELLO: register the contact and answer with HELLO_ACK. */
static void onHello(const Packet& p, int8_t rssi) {
    int c = handshake.onHello(p.header.sensorId, rssi, millis());
    if (c < 0) return;
    Packet out;
    uint8_t payload[4] = { muleId, (uint8_t)(flash.validCount() & 0xFF), 0, 0 };
    packetInit(out, MSG_HELLO, muleId, 0, PRIO_LOW, nowSec(), 60, payload, 4);
    sendTo(udp.remoteIP(), UDP_PORT, out);
    Serial.printf("[DHP] HELLO sensor=%d rssi=%d contact=%d\n",
                  p.header.sensorId, rssi, c);
}

/** Handle SUMMARY: parse candidates and mule chooses the request order. */
static void onSummary(const Packet& p) {
    BufferManager::Candidate candidates[SUMMARY_MAX_ENTRIES];
    uint16_t n = p.header.payloadLen / 5;
    if (n > SUMMARY_MAX_ENTRIES) n = SUMMARY_MAX_ENTRIES;
    for (uint16_t i = 0; i < n; ++i) {
        uint32_t seq;
        memcpy(&seq, p.payload + i * 5, 4);
        candidates[i].seq      = seq;
        candidates[i].priority = p.payload[i * 5 + 4];
        candidates[i].recency  = seq;
    }
    handshake.onSummary(p.header.sensorId, n, millis());

    uint32_t requested[SUMMARY_MAX_ENTRIES];
    uint16_t count = buffer.selectForTransfer(
        candidates, n, WiFi.RSSI(), nowSec(), requested,
        (uint16_t)SUMMARY_MAX_ENTRIES);

    if (count == 0) {
        // Nothing worth transferring: end the contact immediately.
        sendDone(p.header.sensorId);
        return;
    }

    for (uint16_t off = 0; off < count; off += 16) {
        uint16_t chunk = (count - off > 16) ? 16 : (count - off);
        Packet out;
        uint8_t payload[PAYLOAD_MAX];
        for (uint16_t i = 0; i < chunk; ++i)
            memcpy(payload + i * 4, &requested[off + i], 4);
        packetInit(out, MSG_REQ, muleId, 0, PRIO_LOW, nowSec(), 60,
                   payload, chunk * 4);
        sendTo(udp.remoteIP(), UDP_PORT, out);
    }
    Serial.printf("[DHP] SUMMARY sensor=%d candidates=%d requested=%d%s\n",
                  p.header.sensorId, n, count,
                  handshake.degraded(p.header.sensorId) ? " (degraded/HIGH-only)" : "");
}

/** Handle DATA: store before acknowledging. */
static void onData(const Packet& p) {
    handshake.onData(p.header.sensorId, millis());
    if (buffer.admit(p, nowSec())) {
        ++accepted;
        ackSeqs[ackCount++ % 64] = p.header.seq;
        if (ackCount % 8 == 0) sendAck(p.header.sensorId);
    } else {
        ++rejected;
    }
}

void setup() {
    Serial.begin(SERIAL_BAUD);
    pinMode(PIN_STATUS_LED, OUTPUT);
    uint8_t mac[6];
    WiFi.macAddress(mac);
    muleId = mac[5];

    if (!flash.begin()) {
        Serial.println("[FATAL] flash initialisation failed");
        while (true) delay(1000);
    }
    buffer.begin();
    buffer.noteUnload(nowSec());   // deadline-admission horizon

#ifdef BASE_STATION_MODE
    WiFi.mode(WIFI_STA);
    WiFi.begin("YOUR_BASE_SSID", "YOUR_BASE_PASSWORD");
    Serial.println("[BASE] station mode: waiting for infrastructure AP");
#else
    WiFi.mode(WIFI_AP);
    WiFi.softAP(MULE_SSID_PREFIX "01", MULE_PASSWORD, MULE_WIFI_CHANNEL, false, 4);
    IPAddress ip(192, 168, 4, 1);
    WiFi.softAPConfig(ip, ip, IPAddress(255, 255, 255, 0));
    Serial.printf("[MULE] AP %s01 ready at %s, policy=%s\n",
                  MULE_SSID_PREFIX, ip.toString().c_str(),
                  evictionName(EVICTION_POLICY));
#endif
    udp.begin(UDP_PORT);
}

void loop() {
    int len = udp.parsePacket();
    if (len >= (int)PACKET_HEADER_SIZE && len <= (int)sizeof(Packet)) {
        Packet p;
        udp.read((uint8_t*)&p, len);
        if (packetValid(p)) {
            int8_t rssi = WiFi.RSSI();
            switch (p.header.type) {
            case MSG_HELLO:   onHello(p, rssi); break;
            case MSG_SUMMARY: onSummary(p); break;
            case MSG_DATA:    onData(p); break;
            case MSG_DONE:
                handshake.onDone(p.header.sensorId, millis());
                sendDone(p.header.sensorId);
                break;
            default: break;
            }
        }
    }

    // Close contacts that silently disappeared (vehicle left the area).
    if (handshake.expire(millis()) > 0) {
        Packet p;
        uint8_t dummy[1] = {0};
        packetInit(p, MSG_DONE, muleId, 0, PRIO_LOW, nowSec(), 60, dummy, 1);
        sendTo(IPAddress(255, 255, 255, 255), UDP_PORT, p);
    }

    if (millis() - lastStatsMs > 10000) {
        lastStatsMs = millis();
        Serial.printf("[STAT] stored=%u accepted=%u rejected=%u evicted=%u "
                      "expired=%u guardRejects=%u contacts=%u\n",
                      flash.validCount(), accepted, rejected,
                      buffer.evictions(), buffer.expiredPurged(),
                      buffer.lowRejectedByGuard(), handshake.completedContacts());
        digitalWrite(PIN_STATUS_LED, !digitalRead(PIN_STATUS_LED));
    }
}
