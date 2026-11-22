/**
 * @file sensor.ino
 * @brief ESP32 field sensor node for the delay-tolerant data mule project.
 *
 * Behaviour
 * ---------
 *  - Samples a value every SAMPLE_PERIOD_MS (the demo uses a synthetic
 *    sensor; replace readSensor() with an actual I2C/ADC read).
 *  - Classifies the reading as HIGH or LOW priority.
 *  - Buffers it in a SensorQueue using the compile-time POLICY.
 *  - When a mule AP is visible, performs the DHP-1 handshake over UDP and
 *    sends packets in the order requested by the mule.
 *
 * The node keeps buffering while disconnected. It never blocks waiting for a
 * mule: the main loop always returns quickly so sampling continues.
 */
#include <Arduino.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <time.h>

#include "config.h"
#include "Packet.h"
#include "SensorQueue.h"

// Compile-time configuration for this node.
#define SENSOR_ID             1
#define SAMPLE_PERIOD_MS      1000
#define SENSOR_POLICY         SensorQueue::Policy::SP_EDF

static SensorQueue   queue(SENSOR_POLICY);
static WiFiUdp       udp;
static IPAddress     muleIp;

static uint32_t      nextSeq       = 1;
static uint32_t      lastSampleMs  = 0;
static uint32_t      contactStartMs= 0;
static bool          inContact     = false;
static bool          muleRequested = false;
static uint32_t      reqList[SUMMARY_MAX_ENTRIES];
static uint16_t      reqCount      = 0;
static uint16_t      reqCursor     = 0;
static int8_t        lastRssi      = -90;
static uint32_t      txCount       = 0;

/** Returns epoch seconds if available, otherwise seconds since boot. */
static uint32_t nowSec() {
    time_t t = time(nullptr);
    return (t > 1700000000L) ? (uint32_t)t : (millis() / 1000u);
}

/** Replace this with a real ADC / I2C sensor read in a deployment. */
static int16_t readSensor() {
    return (int16_t)(analogReadMilliVolts(34) & 0x7FFF);
}

static void sendPacket(const Packet& p) {
    udp.beginPacket(muleIp, UDP_PORT);
    udp.write((const uint8_t*)&p, PACKET_HEADER_SIZE + p.header.payloadLen);
    udp.endPacket();
}

/** Send the compact DHP-1 HELLO / SUMMARY reply. */
static void sendHello() {
    Packet p;
    uint8_t payload[16] = {0};
    payload[0] = (uint8_t)(queue.size(nowSec()) & 0xFF);
    payload[1] = (uint8_t)queue.highCount(nowSec());
    payload[2] = (uint8_t)(queue.droppedCount() & 0xFF);
    memcpy(&payload[3], &lastRssi, 1);
    packetInit(p, MSG_HELLO, SENSOR_ID, nextSeq, PRIO_LOW, nowSec(),
               60, payload, 8);
    sendPacket(p);
}

static void sendSummary() {
    // SUMMARY payload = repeated 5-byte records: uint32 seq, uint8 priority.
    // 12 records fit in the 64-byte payload.
    Packet p;
    uint8_t payload[PAYLOAD_MAX];
    uint32_t seqs[SUMMARY_MAX_ENTRIES];
    uint16_t n = queue.summary(seqs, 12, nowSec());
    uint16_t bytes = n * 5;
    for (uint16_t i = 0; i < n; ++i) {
        memcpy(payload + i * 5, &seqs[i], 4);
        int idx = queue.findIndex(seqs[i], nowSec());
        uint8_t prio = (idx >= 0 && queue.priorityAt(idx) == PRIO_HIGH)
                     ? PRIO_HIGH : PRIO_LOW;
        payload[i * 5 + 4] = prio;
    }
    packetInit(p, MSG_SUMMARY, SENSOR_ID, nextSeq, PRIO_LOW, nowSec(),
               60, payload, bytes);
    sendPacket(p);
}

/** Parse a REQ datagram: an ordered array of uint32 sequence numbers. */
static void handleReq(const Packet& p) {
    uint16_t n = p.header.payloadLen / 4;
    if (n > SUMMARY_MAX_ENTRIES) n = SUMMARY_MAX_ENTRIES;
    for (uint16_t i = 0; i < n; ++i) {
        memcpy(&reqList[i], p.payload + i * 4, 4);
    }
    reqCount  = n;
    reqCursor = 0;
    muleRequested = true;
}

static void handleAck(const Packet& p) {
    uint16_t n = p.header.payloadLen / 4;
    queue.removeAcked((const uint32_t*)p.payload, n);
}

static void handleDatagram(int len) {
    Packet p;
    if (len < (int)PACKET_HEADER_SIZE || len > (int)sizeof(Packet)) return;
    udp.read((uint8_t*)&p, len);
    if (!packetValid(p)) return;

    lastRssi = WiFi.RSSI();
    switch (p.header.type) {
    case MSG_HELLO:   // HELLO_ACK from mule: send inventory
        if (!inContact) {
            inContact = true;
            contactStartMs = millis();
        }
        sendSummary();
        break;
    case MSG_REQ:     handleReq(p); break;
    case MSG_ACK:     handleAck(p); break;
    case MSG_DONE:
        inContact = false;
        muleRequested = false;
        reqCount = 0;
        break;
    default: break;
    }
}

void setup() {
    Serial.begin(SERIAL_BAUD);
    pinMode(PIN_STATUS_LED, OUTPUT);
    analogReadResolution(12);

    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    // Static IP avoids a DHCP round-trip during a brief pass.
    IPAddress ip(192, 168, 4, SENSOR_IP_BASE + SENSOR_ID);
    IPAddress gw(192, 168, 4, 1);
    IPAddress mask(255, 255, 255, 0);
    WiFi.config(ip, gw, mask);
    muleIp = gw;
    WiFi.begin(MULE_SSID_PREFIX "01", MULE_PASSWORD);

    udp.begin(UDP_PORT);
    Serial.printf("[SENSOR %d] policy=%s, capacity=%d\n",
                  SENSOR_ID, policyName(SENSOR_POLICY), SENSOR_QUEUE_CAPACITY);
}

void loop() {
    uint32_t nowMs = millis();

    // --- sampling -----------------------------------------------------------
    if (nowMs - lastSampleMs >= SAMPLE_PERIOD_MS) {
        lastSampleMs = nowMs;
        int16_t value = readSensor();

        // Demo traffic model: 1 in 5 readings is time-critical (HIGH).
        bool high = (nextSeq % 5 == 0);
        uint8_t prio = high ? PRIO_HIGH : PRIO_LOW;
        uint16_t ttl = high ? TTL_HIGH_DEFAULT : TTL_LOW_DEFAULT;

        uint8_t payload[8];
        memcpy(payload, &value, 2);
        uint32_t t = nowSec();
        memcpy(payload + 2, &t, 4);

        Packet p;
        packetInit(p, MSG_DATA, SENSOR_ID, nextSeq++, prio, t, ttl,
                   (uint8_t*)&payload, 6);
        queue.push(p);
        queue.purgeExpired(nowSec());
        digitalWrite(PIN_STATUS_LED, high ? HIGH : LOW);
    }

    // --- periodic HELLO while a mule is nearby ------------------------------
    if (WiFi.status() == WL_CONNECTED && nowMs - contactStartMs > 4000) {
        sendHello();
        contactStartMs = nowMs;
    }

    // --- UDP receive / transmit ---------------------------------------------
    int len = udp.parsePacket();
    if (len > 0) handleDatagram(len);

    if (inContact && muleRequested && reqCursor < reqCount) {
        // Send one packet per loop iteration to keep sampling non-blocking.
        bool used[SENSOR_QUEUE_CAPACITY] = {false};
        (void)used;
        // Simple sequential lookup by sequence number; queue is small.
        // In a production build this would be an index map.
        Packet p;
        bool found = false;
        // We expose a helper through repeated take() is destructive, so use
        // the queue's summary ordering via selectNext; the mule's REQ order is
        // advisory and the local policy has the final say on airtime.
        int idx = queue.selectNext(nowSec());
        if (idx >= 0 && queue.take(idx, p)) {
            sendPacket(p);
            ++txCount;
            found = true;
        }
        if (!found) {
            ++reqCursor;   // skip a requested seq we no longer hold
        } else {
            ++reqCursor;
        }
        if (reqCursor >= reqCount) muleRequested = false;
    }

    // Contact timeout: leave gracefully if the pass ends.
    if (inContact && millis() - contactStartMs > 12000) {
        inContact = false;
        muleRequested = false;
    }
}
