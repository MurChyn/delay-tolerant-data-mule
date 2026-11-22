/**
 * @file SensorQueue.h
 * @brief Priority-aware bounded queue for sensor readings awaiting a mule pass.
 *
 * Three disciplines are implemented so the firmware can be used to reproduce
 * the simulator's sensor-side comparison on real hardware:
 *
 *   FIFO   - arrival order, the baseline
 *   SP     - strict priority, high class always first
 *   SP_AGE - priority score with an aging term (recommended)
 *
 * The aging term is what prevents low-priority readings from starving when a
 * high-priority sensor is busy: effective score =
 *     (priority == HIGH ? 1 : 0) + (age_seconds / PRIO_AGING_TAU)
 * A low packet becomes as attractive as a fresh high packet after
 * PRIO_AGING_TAU seconds of waiting.
 */
#pragma once

#include <stdint.h>
#include "Packet.h"

class SensorQueue {
public:
    enum class Policy : uint8_t { FIFO = 0, SP = 1, SP_EDF = 2, SP_AGE = 3 };

    struct Slot {
        Packet   packet;
        bool     valid = false;
        uint32_t order = 0;        //!< monotonically increasing arrival index
        uint32_t ttlAtCreation = 0;
    };

    explicit SensorQueue(Policy policy = Policy::SP_AGE);

    /** Insert a packet. Returns false if it was immediately unusable. */
    bool push(const Packet& p);

    /** Number of valid, unexpired packets. */
    uint16_t size(uint32_t now) const;

    /** Number of valid, unexpired HIGH-priority packets. */
    uint16_t highCount(uint32_t now) const;

    /** Index of the packet that should be transmitted next, or -1. */
    int selectNext(uint32_t now) const;

    /** Copy out and invalidate the packet at index i. */
    bool take(int i, Packet& out);

    /** Remove packets acknowledged by the mule. Returns count removed. */
    uint16_t removeAcked(const uint32_t* seqs, uint16_t count);

    /** Remove packets whose TTL has elapsed. Returns count removed. */
    uint16_t purgeExpired(uint32_t now);

    /** Fill a compact list of sequence numbers in transmission order. */
    uint16_t summary(uint32_t* seqs, uint16_t maxEntries, uint32_t now) const;

    /** Locate a buffered packet by sequence number. Returns -1 if absent. */
    int findIndex(uint32_t seq, uint32_t now) const;

    /** Priority class of a buffered slot (call only with a valid index). */
    uint8_t priorityAt(int i) const { return _slots[i].packet.header.priority; }

    void setPolicy(Policy p) { _policy = p; }
    Policy policy() const { return _policy; }
    uint32_t enqueuedCount() const { return _nextOrder; }
    uint32_t droppedCount() const { return _dropped; }

private:
    /** Called when the queue is full: choose a victim using the active policy. */
    int selectVictim(uint32_t now) const;
    bool expired(const Slot& s, uint32_t now) const;

    Slot     _slots[SENSOR_QUEUE_CAPACITY];
    Policy   _policy;
    uint32_t _nextOrder = 0;
    uint32_t _dropped   = 0;
};

/** Human-readable policy name, useful for serial logs. */
const char* policyName(SensorQueue::Policy p);
