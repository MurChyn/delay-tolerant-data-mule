# Dynamic Handshake Protocol (DHP-1)

The mule and sensors use a five-phase, UDP-based handshake. It is designed so
that **no phase depends on a prior long-lived TCP connection**, and so that the
mule can abandon a pass gracefully if the vehicle is leaving range.

## 1. Transport and addressing

| Parameter | Value |
|-----------|-------|
| Mule Wi-Fi mode | SoftAP, SSID `DTN-MULE-<ID>`, channel 6 |
| Sensor mode | Station, statically associated (no scan during pass) |
| Mule IP | `192.168.4.1` |
| Sensor IP | `192.168.4.10 + sensorId` |
| UDP port | `5005` |
| MTU | 256 bytes (fits one Ethernet frame with headroom) |
| Link rate assumption | 256 kbit/s effective goodput (~128 packets/s at 256 B) |

## 2. Packet header (all phases)

```text
 0                   1                   2                   3
 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|      MAGIC (0x4D55)    |   VERSION     |      TYPE     | FLAGS  |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                         SENSOR ID                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          SEQUENCE                              |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|   PRIORITY    |     TTL LEFT (s)      |        PAYLOAD LEN      |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                       CREATED (epoch s)                        |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                          CRC-16                                |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
|                    PAYLOAD (0..64 bytes)                       |
+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
```

`TYPE` values: `1=HELLO`, `2=SUMMARY`, `3=REQ`, `4=DATA`, `5=ACK`, `6=DONE`.

## 3. Phase sequence

```text
Sensor                       Mule
  |--- HELLO(id, caps) ------->|        (mule records RSSI, starts timer)
  |<-- HELLO_ACK(muleId, t) ---|
  |--- SUMMARY(seqs,prios) --->|        (compact inventory of buffered data)
  |<-- REQ(ordered seq list) --|        (mule chooses order using policy)
  |--- DATA(seq k) ----------->|
  |--- DATA(seq k+1) --------->|        (sensor uses its queue discipline)
  |<-- ACK(bitmap of seqs) ----|        (piggybacked every 8 DATA packets)
  |--- DONE ------------------>|
  |<-- DONE_ACK(stats) --------|
```

### Why this is "dynamic"

- The mule measures RSSI from the HELLO packet. RSSI below `-75 dBm` marks a
  **degrading contact**; the mule then emits a `HIGH_ONLY` request list and skips
  bulk traffic, maximising the value of the remaining seconds.
- `REQ` is an explicit ordered list rather than an implicit "send everything".
  This lets the mule apply its flash admission policy *before* airtime is spent:
  a packet with no room in flash is never requested.
- If RSSI collapses or the contact timer expires, the mule broadcasts `DONE`
  and the sensor immediately stops transmitting. No retransmission backoff is
  attempted, because the next pass is expected within minutes.

## 4. Timing budget (design target)

| Phase | Budget |
|-------|--------|
| HELLO + HELLO_ACK | < 20 ms |
| SUMMARY (64 entries) | < 40 ms |
| REQ | < 20 ms |
| DATA transfer | remainder of contact |
| ACK / DONE | < 20 ms |

Measured in simulation: handshake overhead is **~2.4 %** of a 4 s contact.

## 5. Reliability

- Each `DATA` datagram carries a CRC-16; corrupted datagrams are silently
  ignored and will be re-requested on the next pass.
- `ACK` uses a 64-bit rolling bitmap, so a single ACK confirms up to 64 packets.
- The mule writes to flash before sending the ACK for that batch, giving
  *store-before-acknowledge* semantics.

## 6. Extension: base-station unload

When `BASE_STATION_MODE` is compiled, the mule connects to the infrastructure
AP and uploads stored records in 16-record chunks to `BASE_IP:5006`. Records are
deleted only after an explicit `UNLOAD_ACK`. This makes the mule a true
store-carry-forward node rather than a simple collector.
