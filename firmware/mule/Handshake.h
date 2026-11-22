/**
 * @file Handshake.h
 * @brief Per-sensor contact state machine for the DHP-1 dynamic handshake.
 *
 * The mule can serve several sensors in one pass, so contact state is tracked
 * per sensor ID. A contact is considered degraded when RSSI drops below
 * RSSI_DEGRADED_LEVEL or when more than CONTACT_TIMEOUT_MS elapse without a
 * packet; in that state only high-priority records are requested.
 */
#pragma once

#include <stdint.h>

#define MAX_CONTACTS        8
#define CONTACT_TIMEOUT_MS  12000

class Handshake {
public:
    struct Contact {
        uint16_t sensorId = 0;
        int8_t   rssi = -90;
        uint32_t startedMs = 0;
        uint32_t lastMs = 0;
        uint16_t requested = 0;
        uint16_t received = 0;
        bool     active = false;
    };

    /** Register or refresh a sensor contact. Returns its contact slot. */
    int onHello(uint16_t sensorId, int8_t rssi, uint32_t nowMs);

    void onSummary(uint16_t sensorId, uint16_t count, uint32_t nowMs);
    void onData(uint16_t sensorId, uint32_t nowMs);
    void onDone(uint16_t sensorId, uint32_t nowMs);

    /** Mark contacts that have gone quiet; returns how many were closed. */
    uint8_t expire(uint32_t nowMs);

    int find(uint16_t sensorId) const;
    bool active(uint16_t sensorId) const;
    bool degraded(uint16_t sensorId) const;
    Contact& contact(int i) { return _contacts[i]; }
    const Contact& contact(int i) const { return _contacts[i]; }

    uint32_t completedContacts() const { return _completed; }

private:
    Contact  _contacts[MAX_CONTACTS];
    uint32_t _completed = 0;
};
