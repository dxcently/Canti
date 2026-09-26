// BLE GATT peripheral, exactly as android/PROTOCOL.md "BLE GATT link (v1)".
//   advertising name VOX-XXXX (last 2 address bytes), service UUID in the advertisement
//   EVENT  notify  fragmented feature messages: [header][UTF-8 chunk], header bit 7 = last, bit 6 = first,
//                  bits 0-5 = counter mod 64 (0 for the first notification of each connection)
//   CONFIG write   JSON from the phone (unknown keys ignored)
//   INFO   read    {"v":1,"fw":...,"mic":...,"fp_version":null}
// Security: LE Secure Connections bonding, Just Works; EVENT (its CCCD) and CONFIG need an encrypted link.
// Pairing gate: a new pairing is accepted only while the pairing window is open (ble_set_pairing_window); bonded
// phones re-encrypt at any time.
// A VOX_INSECURE build drops the encryption requirement and says "insecure":true in INFO.
//
// Power: ble_power_off() powers the CYW43 radio chip down completely (sleep); ble_power_on() brings it and BTstack
// back. While off, every function here is safe to call and reports "not connected".
//
// Threading: BTstack runs in the CYW43 async context. Everything here that touches BTstack takes BluetoothLock.
// BTstack callbacks never print; they log into a ring that ble_poll() prints from loop().
#pragma once
#include <Arduino.h>

struct BleStatus {
    bool powered;         // the radio chip is on (false while asleep)
    bool up;              // controller running, advertising or connected
    bool pair_window;     // new pairing requests are accepted
    bool connected;
    bool encrypted;
    bool secure_conn;     // the link uses LE Secure Connections
    bool bonded;
    bool notify;          // EVENT notifications enabled by the central
    uint16_t mtu;
    uint16_t conn_interval_x125;  // units of 1.25 ms
    uint8_t key_size;
    uint16_t max_mtu;     // what we will accept on the next connection
    uint32_t sent_msgs, sent_frags, dropped_msgs;
    uint8_t queued;
    int bonds;            // stored bonds (-1 while the radio is off)
    char name[12];
    char addr[18];
};

void ble_begin();                      // setup(): the core has already powered the CYW43 up
void ble_poll();                       // from loop(): prints BT-context log lines, runs deferred work
bool ble_ready();                      // connected, notifications on, and (secure build) encrypted
bool ble_connected();
bool ble_tx_idle();                    // no message queued or in flight
bool ble_send(const char *msg, size_t len);   // queue one whole message; false if not ready or full
void ble_set_info(const char *json);
void ble_status(BleStatus *st);
void ble_set_max_mtu(uint16_t mtu);    // applies to the next connection
void ble_disconnect();
int ble_forget_bonds();                // returns how many were removed (-1: radio off)
void ble_set_pairing_window(bool open);
bool ble_pairing_window();
void ble_power_off();                  // drops the link, then powers the radio chip down
bool ble_power_on();                   // false if the chip failed to start
bool ble_powered();

// Hooks implemented by the sketch (called from loop() context, via ble_poll()).
void on_ble_ready();                   // notifications just got enabled: send the current state
void on_ble_disconnected();
void on_ble_bonded();                  // a new bond was made while the pairing window was open
void on_ble_config(const char *json, size_t len);
