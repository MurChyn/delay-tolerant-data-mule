/**
 * @file FlashStore.h
 * @brief Fixed-slot, wear-levelled record store backed by LittleFS.
 *
 * The store is a single pre-allocated binary file. Each logical slot is
 * FLASH_RECORD_SIZE bytes, so a write never shifts other records. Eviction
 * therefore costs exactly one flash page write, which is important when the
 * mule only has a few seconds of contact time and cannot afford a compaction.
 */
#pragma once

#include <stdint.h>
#include "Packet.h"

class FlashStore {
public:
    static constexpr const char* PATH = "/mule_store.bin";

    /** Mount LittleFS and create/expand the backing file. */
    bool begin();

    /** Read slot contents. Returns false for an out-of-range slot. */
    bool read(uint16_t slot, FlashRecord& out);

    /** Write a full record to a slot and flush it. */
    bool write(uint16_t slot, const FlashRecord& rec);

    /** Mark a slot invalid (single byte write, cheap on flash). */
    bool invalidate(uint16_t slot);

    /** Erase all records but keep the file allocated. */
    void format();

    /** Number of slots currently marked valid. */
    uint16_t validCount() const { return _validCount; }

    /** Total usable slots. */
    static constexpr uint16_t capacity() { return MULE_FLASH_RECORDS; }

    /** Raw byte size of the backing file. */
    static uint32_t fileSize() { return (uint32_t)MULE_FLASH_RECORDS * FLASH_RECORD_SIZE; }

private:
    uint16_t _validCount = 0;
};

/** Build a FlashRecord with correct CRC for a packet. */
FlashRecord makeRecord(uint16_t slot, const Packet& p, uint32_t storedAt);
