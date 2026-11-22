/**
 * @file Packet.h
 * @brief Wire and storage representation of a single sensor reading.
 *
 * The struct is packed so it has the same layout on every ESP32 and in the
 * host-side simulator. Reserved bytes pad the record to FLASH_RECORD_SIZE so a
 * flash slot can be rewritten without touching its neighbours.
 */
#pragma once

#include <stdint.h>
#include <string.h>
#include "config.h"

// Header is 20 bytes on the wire:
//   magic(2) version(1) type(1) flags(1) sensorId(2) seq(4)
//   priority(1) ttlLeft(2) payloadLen(2) created(4) = 20 bytes
struct __attribute__((packed)) PacketHeader {
    uint16_t magic;       //!< PACKET_MAGIC
    uint8_t  version;     //!< PACKET_VERSION
    uint8_t  type;        //!< MSG_*
    uint8_t  flags;       //!< bit 0 = HIGH_ONLY request, bit 1 = compressed
    uint16_t sensorId;    //!< originating sensor
    uint32_t seq;         //!< monotonic sequence number per sensor
    uint8_t  priority;    //!< PRIO_LOW or PRIO_HIGH
    uint16_t ttlLeft;     //!< seconds of validity remaining
    uint16_t payloadLen;  //!< bytes of payload following the header
    uint32_t created;     //!< Unix epoch seconds when sampled
};

struct __attribute__((packed)) Packet {
    PacketHeader header;
    uint8_t payload[PAYLOAD_MAX];
};

/** A fixed-size record stored in flash. */
struct __attribute__((packed)) FlashRecord {
    uint32_t slot;        //!< physical slot index (for integrity checks)
    uint32_t crc32;       //!< CRC of the Packet portion
    uint32_t storedAt;    //!< epoch seconds when written
    uint8_t  valid;       //!< 1 = live record, 0 = erased/invalid
    uint8_t  reserved[3];
    Packet   packet;
};

static_assert(sizeof(PacketHeader) == PACKET_HEADER_SIZE,
              "PacketHeader must match the documented wire layout");
static_assert(sizeof(FlashRecord) <= FLASH_RECORD_SIZE,
              "FlashRecord must fit in one flash record");

/** Fill in the constant fields of a data packet. */
inline void packetInit(Packet& p, uint8_t type, uint16_t sensorId,
                       uint32_t seq, uint8_t priority, uint32_t created,
                       uint16_t ttlSeconds, const uint8_t* payload,
                       uint16_t len) {
    memset(&p, 0, sizeof(p));
    p.header.magic      = PACKET_MAGIC;
    p.header.version    = PACKET_VERSION;
    p.header.type       = type;
    p.header.flags      = 0;
    p.header.sensorId   = sensorId;
    p.header.seq        = seq;
    p.header.priority   = priority;
    p.header.ttlLeft    = (uint16_t)(ttlSeconds > 65535 ? 65535 : ttlSeconds);
    p.header.payloadLen = (uint16_t)(len > PAYLOAD_MAX ? PAYLOAD_MAX : len);
    p.header.created    = created;
    if (payload && len) {
        memcpy(p.payload, payload, p.header.payloadLen);
    }
}

/** Return true if the header looks like a valid DHP-1 packet. */
inline bool packetValid(const Packet& p) {
    return p.header.magic == PACKET_MAGIC &&
           p.header.version == PACKET_VERSION &&
           p.header.payloadLen <= PAYLOAD_MAX;
}

/**
 * CRC-16/CCITT-FALSE. Used on the wire because it is cheap to compute on an
 * ESP32 and detects all burst errors up to 16 bits.
 */
inline uint16_t crc16(const uint8_t* data, size_t len, uint16_t crc = 0xFFFF) {
    while (len--) {
        crc ^= (uint16_t)(*data++) << 8;
        for (int i = 0; i < 8; ++i) {
            crc = (crc & 0x8000) ? (uint16_t)((crc << 1) ^ 0x1021)
                                : (uint16_t)(crc << 1);
        }
    }
    return crc;
}

/** CRC-32 (IEEE 802.3) used for flash integrity checks. */
inline uint32_t crc32(const uint8_t* data, size_t len) {
    uint32_t crc = 0xFFFFFFFFu;
    while (len--) {
        crc ^= *data++;
        for (int i = 0; i < 8; ++i) {
            crc = (crc & 1u) ? (crc >> 1) ^ 0xEDB88320u : (crc >> 1);
        }
    }
    return ~crc;
}
