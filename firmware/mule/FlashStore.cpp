/**
 * @file FlashStore.cpp
 * @brief Implementation of the fixed-slot flash record store.
 */
#include "FlashStore.h"
#include <Arduino.h>
#include <LittleFS.h>
#include <stddef.h>
#include "config.h"

bool FlashStore::begin() {
    if (!LittleFS.begin(true)) {
        Serial.println("[FLASH] LittleFS mount failed");
        return false;
    }

    File f = LittleFS.open(PATH, "r+");
    if (!f) {
        f = LittleFS.open(PATH, "w");
        if (!f) return false;
        f.truncate(fileSize());
    }
    if (f.size() < fileSize()) f.truncate(fileSize());
    f.close();

    // Count valid records on startup (cheap sequential scan of the index
    // bytes only in a real implementation; here we read whole records once).
    _validCount = 0;
    f = LittleFS.open(PATH, "r");
    if (!f) return false;
    FlashRecord rec;
    for (uint16_t i = 0; i < MULE_FLASH_RECORDS; ++i) {
        f.seek((uint32_t)i * FLASH_RECORD_SIZE);
        f.read((uint8_t*)&rec, sizeof(rec));
        if (rec.valid == 1 && rec.slot == i &&
            rec.crc32 == crc32((const uint8_t*)&rec.packet, sizeof(Packet))) {
            ++_validCount;
        } else if (rec.valid != 0) {
            // Repair a torn record from an interrupted write.
            invalidate(i);
        }
    }
    f.close();
    Serial.printf("[FLASH] mounted, %d/%d records valid (%u bytes)\n",
                  _validCount, MULE_FLASH_RECORDS, fileSize());
    return true;
}

bool FlashStore::read(uint16_t slot, FlashRecord& out) {
    if (slot >= MULE_FLASH_RECORDS) return false;
    File f = LittleFS.open(PATH, "r");
    if (!f) return false;
    f.seek((uint32_t)slot * FLASH_RECORD_SIZE);
    int n = f.read((uint8_t*)&out, sizeof(out));
    f.close();
    return n == (int)sizeof(out);
}

bool FlashStore::write(uint16_t slot, const FlashRecord& rec) {
    if (slot >= MULE_FLASH_RECORDS) return false;
    File f = LittleFS.open(PATH, "r+");
    if (!f) return false;
    f.seek((uint32_t)slot * FLASH_RECORD_SIZE);
    size_t n = f.write((const uint8_t*)&rec, sizeof(rec));
    bool ok = (n == sizeof(rec));
    f.flush();
    f.close();
    if (ok) ++_validCount;
    return ok;
}

bool FlashStore::invalidate(uint16_t slot) {
    if (slot >= MULE_FLASH_RECORDS) return false;
    File f = LittleFS.open(PATH, "r+");
    if (!f) return false;
    f.seek((uint32_t)slot * FLASH_RECORD_SIZE + offsetof(FlashRecord, valid));
    size_t n = f.write((const uint8_t*)"\0", 1);
    f.flush();
    f.close();
    if (n == 1 && _validCount > 0) --_validCount;
    return n == 1;
}

void FlashStore::format() {
    LittleFS.remove(PATH);
    File f = LittleFS.open(PATH, "w");
    if (f) { f.truncate(fileSize()); f.close(); }
    _validCount = 0;
    Serial.println("[FLASH] store formatted");
}

FlashRecord makeRecord(uint16_t slot, const Packet& p, uint32_t storedAt) {
    FlashRecord r = {};
    r.slot     = slot;
    r.crc32    = crc32((const uint8_t*)&p, sizeof(Packet));
    r.storedAt = storedAt;
    r.valid    = 1;
    r.packet   = p;
    return r;
}
