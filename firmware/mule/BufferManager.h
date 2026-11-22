/**
 * @file BufferManager.h
 * @brief Mule-side flash admission, eviction and transfer-order policy.
 *
 * This is the embedded implementation of the policy evaluated in
 * simulator/dtn_sim.py. The recommended configuration is PADS:
 *
 *   1. Expired records are invalidated first (zero value).
 *   2. A guard band of HP_GUARD_SLOTS is reserved for high-priority arrivals.
 *   3. When full, the record with the lowest value score is evicted:
 *        score = priority + age / PRIO_AGING_TAU
 *      (so an old low-priority record is evicted before a fresh one).
 *   4. Within a class, the record closest to expiry is evicted first.
 */
#pragma once

#include <stdint.h>
#include "Packet.h"
#include "FlashStore.h"

class BufferManager {
public:
    enum class Eviction : uint8_t {
        DROP_TAIL = 0,     //!< reject new arrival when full
        DROP_OLDEST = 1,   //!< evict globally oldest record
        DROP_LOWEST = 2,   //!< evict lowest priority, then oldest
        PADS = 3           //!< priority-aware drop with aging + guard band
    };

    struct Meta {
        uint32_t seq;
        uint16_t sensorId;
        uint8_t  priority;
        uint8_t  valid;
        uint32_t created;
        uint32_t expiresAt;
        uint32_t storedAt;
        uint16_t slot;
    };

    struct Candidate {
        uint32_t seq;
        uint8_t  priority;
        uint32_t recency;   //!< proxy for age; higher seq = more recent
    };

    explicit BufferManager(FlashStore& store, Eviction policy = Eviction::PADS);

    /** Prepare the in-RAM index from flash (call after store.begin()). */
    bool begin();

    /** Record an unload; updates the deadline-admission horizon. */
    void noteUnload(uint32_t now) { _nextUnload = now + UNLOAD_INTERVAL_SEC; }

    /**
     * Admit a packet into flash.
     * @return true if it was stored (possibly after evicting a victim).
     */
    bool admit(const Packet& p, uint32_t now);

    /** Choose the ordered request list for a sensor's SUMMARY. */
    uint16_t selectForTransfer(const Candidate* candidates, uint16_t count,
                               int8_t rssi, uint32_t now,
                               uint32_t* outSeqs, uint16_t maxOut) const;

    /** Number of live records in the RAM index. */
    uint16_t liveCount() const { return _live; }

    void setPolicy(Eviction p) { _policy = p; }
    Eviction policy() const { return _policy; }
    uint32_t evictions() const { return _evictions; }
    uint32_t expiredPurged() const { return _expiredPurged; }
    uint32_t lowRejectedByGuard() const { return _guardRejects; }
    uint32_t doomedRejects() const { return _doomedRejects; }

    /** Find the metadata for a sequence number, if present. */
    bool find(uint32_t seq, Meta& out) const;

private:
    int findFreeSlot() const;
    int chooseVictim(const Packet& incoming, uint32_t now) const;
    uint16_t purgeExpired(uint32_t now);
    double valueScore(const Meta& m, uint32_t now) const;

    FlashStore& _store;
    Eviction    _policy;
    Meta        _index[MULE_FLASH_RECORDS];
    uint16_t    _live = 0;
    uint32_t    _evictions = 0;
    uint32_t    _expiredPurged = 0;
    uint32_t    _guardRejects = 0;
    uint32_t    _doomedRejects = 0;
    uint32_t    _nextUnload = 0;
};

const char* evictionName(BufferManager::Eviction e);
