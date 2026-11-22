/**
 * @file SensorQueue.cpp
 * @brief Implementation of the sensor-side buffer disciplines.
 */
#include "SensorQueue.h"
#include "config.h"
#include <math.h>

SensorQueue::SensorQueue(Policy policy) : _policy(policy) {}

bool SensorQueue::expired(const Slot& s, uint32_t now) const {
    if (!s.valid) return true;
    // 32-bit wrap-safe elapsed time.
    uint32_t ttl = s.ttlAtCreation;
    return (uint32_t)(now - s.packet.header.created) > ttl;
}

bool SensorQueue::push(const Packet& p) {
    if (p.header.payloadLen > PAYLOAD_MAX) return false;

    int target = -1;
    for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
        if (!_slots[i].valid) { target = i; break; }
    }
    if (target < 0) {
        target = selectVictim(0);   // 0 = do not treat as expired; pick by score
        if (target < 0) { ++_dropped; return false; }
        ++_dropped;
    }

    Slot& s = _slots[target];
    s.packet         = p;
    s.valid          = true;
    s.order          = _nextOrder++;
    s.ttlAtCreation  = p.header.ttlLeft;
    return true;
}

int SensorQueue::selectVictim(uint32_t now) const {
    // Prefer the least valuable packet: expired first, then lowest score.
    int best = -1;
    double bestScore = 1e30;
    for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
        const Slot& s = _slots[i];
        if (!s.valid) continue;
        if (expired(s, now)) return i;

        double age = (double)(now - s.packet.header.created);
        double score = (s.packet.header.priority == PRIO_HIGH ? 1.0 : 0.0)
                     + age / (double)PRIO_AGING_TAU;
        if (score < bestScore) { bestScore = score; best = i; }
    }
    return best;
}

uint16_t SensorQueue::size(uint32_t now) const {
    uint16_t n = 0;
    for (const Slot& s : _slots) if (s.valid && !expired(s, now)) ++n;
    return n;
}

uint16_t SensorQueue::highCount(uint32_t now) const {
    uint16_t n = 0;
    for (const Slot& s : _slots) {
        if (s.valid && !expired(s, now) && s.packet.header.priority == PRIO_HIGH) ++n;
    }
    return n;
}

int SensorQueue::selectNext(uint32_t now) const {
    int best = -1;

    switch (_policy) {
    case Policy::FIFO:
        for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
            const Slot& s = _slots[i];
            if (!s.valid || expired(s, now)) continue;
            if (best < 0 || s.order < _slots[best].order) best = i;
        }
        break;

    case Policy::SP:
        for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
            const Slot& s = _slots[i];
            if (!s.valid || expired(s, now)) continue;
            if (best < 0) { best = i; continue; }
            const Slot& b = _slots[best];
            if (s.packet.header.priority > b.packet.header.priority ||
                (s.packet.header.priority == b.packet.header.priority &&
                 s.order < b.order)) {
                best = i;
            }
        }
        break;

    case Policy::SP_EDF:
        // High class first; inside a class send the packet closest to its
        // deadline first. This is the recommended sensor-side discipline.
        for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
            const Slot& s = _slots[i];
            if (!s.valid || expired(s, now)) continue;
            if (best < 0) { best = i; continue; }
            const Slot& b = _slots[best];
            uint8_t pi = s.packet.header.priority;
            uint8_t pb = b.packet.header.priority;
            uint32_t ei = s.packet.header.created + s.ttlAtCreation;
            uint32_t eb = b.packet.header.created + b.ttlAtCreation;
            if (pi > pb || (pi == pb && ei < eb) ||
                (pi == pb && ei == eb && s.order < b.order)) {
                best = i;
            }
        }
        break;

    case Policy::SP_AGE:
    default: {
        double bestScore = -1e30;
        for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
            const Slot& s = _slots[i];
            if (!s.valid || expired(s, now)) continue;

            double age = (double)(now - s.packet.header.created);
            double score = (s.packet.header.priority == PRIO_HIGH ? 1.0 : 0.0)
                         + age / (double)PRIO_AGING_TAU;
            if (score > bestScore ||
                (score == bestScore && best >= 0 && s.order < _slots[best].order)) {
                bestScore = score;
                best = i;
            }
        }
        break;
    }
    }
    return best;
}

bool SensorQueue::take(int i, Packet& out) {
    if (i < 0 || i >= SENSOR_QUEUE_CAPACITY || !_slots[i].valid) return false;
    out = _slots[i].packet;
    _slots[i].valid = false;
    return true;
}

uint16_t SensorQueue::removeAcked(const uint32_t* seqs, uint16_t count) {
    uint16_t removed = 0;
    for (uint16_t j = 0; j < count; ++j) {
        for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
            if (_slots[i].valid && _slots[i].packet.header.seq == seqs[j]) {
                _slots[i].valid = false;
                ++removed;
                break;
            }
        }
    }
    return removed;
}

uint16_t SensorQueue::purgeExpired(uint32_t now) {
    uint16_t n = 0;
    for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
        if (_slots[i].valid && expired(_slots[i], now)) {
            _slots[i].valid = false;
            ++n;
        }
    }
    return n;
}

uint16_t SensorQueue::summary(uint32_t* seqs, uint16_t maxEntries,
                              uint32_t now) const {
    uint16_t n = 0;
    // Collect indices then sort them by selectNext's ordering by repeatedly
    // choosing the best remaining index. Capacity is small (<= 128), so this
    // is acceptable on an ESP32 and keeps the code identical to the simulator.
    bool used[SENSOR_QUEUE_CAPACITY] = {false};
    for (uint16_t k = 0; k < maxEntries; ++k) {
        int best = -1;
        for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
            if (used[i] || !_slots[i].valid || expired(_slots[i], now)) continue;
            if (best < 0) { best = i; continue; }
            uint8_t pi = _slots[i].packet.header.priority;
            uint8_t pb = _slots[best].packet.header.priority;
            if (pi > pb || (pi == pb && _slots[i].order < _slots[best].order)) {
                best = i;
            }
        }
        if (best < 0) break;
        used[best] = true;
        seqs[n++] = _slots[best].packet.header.seq;
    }
    return n;
}

int SensorQueue::findIndex(uint32_t seq, uint32_t now) const {
    for (int i = 0; i < SENSOR_QUEUE_CAPACITY; ++i) {
        if (_slots[i].valid && !expired(_slots[i], now) &&
            _slots[i].packet.header.seq == seq) {
            return i;
        }
    }
    return -1;
}

const char* policyName(SensorQueue::Policy p) {
    switch (p) {
    case SensorQueue::Policy::FIFO:   return "FIFO";
    case SensorQueue::Policy::SP:     return "SP";
    case SensorQueue::Policy::SP_EDF: return "SP-EDF";
    case SensorQueue::Policy::SP_AGE: return "SP-AGE";
    default:                          return "UNKNOWN";
    }
}
