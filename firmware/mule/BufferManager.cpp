/**
 * @file BufferManager.cpp
 * @brief Implementation of mule-side admission and eviction policies.
 */
#include "BufferManager.h"
#include <Arduino.h>
#include "config.h"
#include <math.h>

BufferManager::BufferManager(FlashStore& store, Eviction policy)
    : _store(store), _policy(policy) {}

bool BufferManager::begin() {
    _live = 0;
    for (uint16_t slot = 0; slot < FlashStore::capacity(); ++slot) {
        FlashRecord rec;
        if (!_store.read(slot, rec)) continue;
        if (rec.valid != 1 || rec.slot != slot) continue;
        if (rec.crc32 != crc32((const uint8_t*)&rec.packet, sizeof(Packet))) continue;

        Meta& m = _index[_live++];
        m.seq       = rec.packet.header.seq;
        m.sensorId  = rec.packet.header.sensorId;
        m.priority  = rec.packet.header.priority;
        m.valid     = 1;
        m.created   = rec.packet.header.created;
        m.expiresAt = rec.packet.header.created + rec.packet.header.ttlLeft;
        m.storedAt  = rec.storedAt;
        m.slot      = slot;
    }
    Serial.printf("[BUF] index rebuilt: %d live records\n", _live);
    return true;
}

bool BufferManager::find(uint32_t seq, Meta& out) const {
    for (uint16_t i = 0; i < _live; ++i) {
        if (_index[i].valid && _index[i].seq == seq) {
            out = _index[i];
            return true;
        }
    }
    return false;
}

double BufferManager::valueScore(const Meta& m, uint32_t now) const {
    double age = (double)(now - m.created);
    return (m.priority == PRIO_HIGH ? 1.0 : 0.0)
         + age / (double)PRIO_AGING_TAU;
}

uint16_t BufferManager::purgeExpired(uint32_t now) {
    uint16_t removed = 0;
    for (uint16_t i = 0; i < _live; ++i) {
        Meta& m = _index[i];
        if (!m.valid) continue;
        if ((uint32_t)(now - m.expiresAt) < 0x80000000u) {
            _store.invalidate(m.slot);
            m.valid = 0;
            ++removed;
        }
    }
    if (removed) {
        // Compact the index so _live always equals the number of valid metas.
        uint16_t w = 0;
        for (uint16_t i = 0; i < _live; ++i) {
            if (_index[i].valid) _index[w++] = _index[i];
        }
        _live = w;
        _expiredPurged += removed;
    }
    return removed;
}

int BufferManager::findFreeSlot() const {
    bool used[FlashStore::capacity()] = {false};
    for (uint16_t i = 0; i < _live; ++i) {
        if (_index[i].valid && _index[i].slot < FlashStore::capacity()) {
            used[_index[i].slot] = true;
        }
    }
    for (uint16_t s = 0; s < FlashStore::capacity(); ++s) {
        if (!used[s]) return s;
    }
    return -1;
}

/** @return slot index of victim, -1 if no victim, -2 if arrival is rejected. */
int BufferManager::chooseVictim(const Packet& incoming, uint32_t now) const {
    if (_policy == Eviction::DROP_TAIL) return -2;

    // Guard band: keep free slots for future high-priority arrivals.
    if (_policy == Eviction::PADS && incoming.header.priority == PRIO_LOW &&
        _live >= (uint16_t)(FlashStore::capacity() - HP_GUARD_SLOTS)) {
        return -2;
    }

    int victimMeta = -1;
    switch (_policy) {
    case Eviction::DROP_OLDEST:
        for (uint16_t i = 0; i < _live; ++i) {
            if (victimMeta < 0 || _index[i].storedAt < _index[victimMeta].storedAt)
                victimMeta = i;
        }
        break;

    case Eviction::DROP_LOWEST:
        for (uint16_t i = 0; i < _live; ++i) {
            if (victimMeta < 0) { victimMeta = i; continue; }
            if (_index[i].priority < _index[victimMeta].priority ||
                (_index[i].priority == _index[victimMeta].priority &&
                 _index[i].storedAt < _index[victimMeta].storedAt)) {
                victimMeta = i;
            }
        }
        break;

    case Eviction::PADS:
    default: {
        double worst = 1e30;
        for (uint16_t i = 0; i < _live; ++i) {
            double score = valueScore(_index[i], now);
            if (score < worst ||
                (score == worst && victimMeta >= 0 &&
                 _index[i].expiresAt < _index[victimMeta].expiresAt)) {
                worst = score;
                victimMeta = i;
            }
        }
        break;
    }
    }
    return victimMeta < 0 ? -1 : (int)_index[victimMeta].slot;
}

bool BufferManager::admit(const Packet& p, uint32_t now) {
    purgeExpired(now);

    // Deadline-aware admission: a record that expires before the next unload
    // can never be delivered, so never spend a slot (or flash writes) on it.
    if (_policy == Eviction::PADS && _nextUnload != 0 &&
        (uint32_t)(p.header.created + p.header.ttlLeft - _nextUnload) < 0x80000000u) {
        ++_doomedRejects;
        return false;
    }

    int slot = findFreeSlot();
    if (slot < 0) {
        slot = chooseVictim(p, now);
        if (slot <= -1) {
            if (slot == -2 && p.header.priority == PRIO_LOW) ++_guardRejects;
            return false;
        }
        ++_evictions;
    }

    FlashRecord rec = makeRecord((uint16_t)slot, p, now);
    if (!_store.write((uint16_t)slot, rec)) return false;

    // Replace or append the RAM metadata for this slot.
    uint16_t i = 0;
    for (; i < _live; ++i) {
        if (_index[i].slot == slot) break;
    }
    if (i == _live) ++_live;

    Meta& m = _index[i];
    m.seq       = p.header.seq;
    m.sensorId  = p.header.sensorId;
    m.priority  = p.header.priority;
    m.valid     = 1;
    m.created   = p.header.created;
    m.expiresAt = p.header.created + p.header.ttlLeft;
    m.storedAt  = now;
    m.slot      = (uint16_t)slot;
    return true;
}

uint16_t BufferManager::selectForTransfer(const Candidate* candidates,
                                          uint16_t count, int8_t rssi,
                                          uint32_t now, uint32_t* outSeqs,
                                          uint16_t maxOut) const {
    struct Ranked { uint32_t seq; double score; uint8_t prio; };
    Ranked ranked[SUMMARY_MAX_ENTRIES];
    uint16_t n = 0;
    bool degraded = (rssi < RSSI_DEGRADED_LEVEL);

    for (uint16_t i = 0; i < count && n < SUMMARY_MAX_ENTRIES; ++i) {
        if (degraded && candidates[i].priority != PRIO_HIGH) continue;

        Meta existing;
        if (find(candidates[i].seq, existing)) continue;  // already stored

        // Prefer high priority; use recency as an age proxy because SUMMARY
        // carries sequence numbers rather than full timestamps.
        double score = (candidates[i].priority == PRIO_HIGH ? 1.0 : 0.0)
                     + (double)(candidates[i].recency % 4096) / 4096.0 / PRIO_AGING_TAU;
        (void)now;
        ranked[n].seq   = candidates[i].seq;
        ranked[n].score = score;
        ranked[n].prio  = candidates[i].priority;
        ++n;
    }

    // Insertion sort, descending value.
    for (uint16_t i = 1; i < n; ++i) {
        Ranked key = ranked[i];
        int j = (int)i - 1;
        while (j >= 0 && ranked[j].score < key.score) {
            ranked[j + 1] = ranked[j];
            --j;
        }
        ranked[j + 1] = key;
    }

    uint16_t limit = maxOut;
    if (degraded && limit > 8) limit = 8;
    if (limit > n) limit = n;
    for (uint16_t i = 0; i < limit; ++i) outSeqs[i] = ranked[i].seq;
    return limit;
}

const char* evictionName(BufferManager::Eviction e) {
    switch (e) {
    case BufferManager::Eviction::DROP_TAIL:   return "DROP-TAIL";
    case BufferManager::Eviction::DROP_OLDEST: return "DROP-OLDEST";
    case BufferManager::Eviction::DROP_LOWEST: return "DROP-LOWEST";
    case BufferManager::Eviction::PADS:        return "PADS";
    default:                                   return "UNKNOWN";
    }
}
