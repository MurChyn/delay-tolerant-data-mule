/**
 * @file Handshake.cpp
 * @brief Contact tracking for the DHP-1 handshake.
 */
#include "Handshake.h"
#include "config.h"

int Handshake::find(uint16_t sensorId) const {
    for (int i = 0; i < MAX_CONTACTS; ++i) {
        if (_contacts[i].active && _contacts[i].sensorId == sensorId) return i;
    }
    return -1;
}

int Handshake::onHello(uint16_t sensorId, int8_t rssi, uint32_t nowMs) {
    int i = find(sensorId);
    if (i < 0) {
        for (int k = 0; k < MAX_CONTACTS; ++k) {
            if (!_contacts[k].active) { i = k; break; }
        }
    }
    if (i < 0) return -1;   // all contact slots busy

    Contact& c = _contacts[i];
    if (!c.active) {
        c = Contact{};
        c.active = true;
        c.sensorId = sensorId;
        c.startedMs = nowMs;
    }
    c.rssi = rssi;
    c.lastMs = nowMs;
    return i;
}

void Handshake::onSummary(uint16_t sensorId, uint16_t count, uint32_t nowMs) {
    int i = find(sensorId);
    if (i < 0) return;
    _contacts[i].requested = count;
    _contacts[i].lastMs = nowMs;
}

void Handshake::onData(uint16_t sensorId, uint32_t nowMs) {
    int i = find(sensorId);
    if (i < 0) return;
    ++_contacts[i].received;
    _contacts[i].lastMs = nowMs;
}

void Handshake::onDone(uint16_t sensorId, uint32_t nowMs) {
    int i = find(sensorId);
    if (i < 0) return;
    (void)nowMs;
    _contacts[i].active = false;
    ++_completed;
}

uint8_t Handshake::expire(uint32_t nowMs) {
    uint8_t closed = 0;
    for (int i = 0; i < MAX_CONTACTS; ++i) {
        if (_contacts[i].active &&
            (uint32_t)(nowMs - _contacts[i].lastMs) > CONTACT_TIMEOUT_MS) {
            _contacts[i].active = false;
            ++_completed;
            ++closed;
        }
    }
    return closed;
}

bool Handshake::active(uint16_t sensorId) const { return find(sensorId) >= 0; }

bool Handshake::degraded(uint16_t sensorId) const {
    int i = find(sensorId);
    if (i < 0) return true;
    return _contacts[i].rssi < RSSI_DEGRADED_LEVEL;
}
