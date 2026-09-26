// BLE GATT link v1 on raw BTstack (the core's BLE library only offers legacy Just Works). See ble_link.h.
#include "ble_link.h"
#include "config.h"
#include "out.h"
#include <stdarg.h>
#include <btstack.h>
#include <ble/att_db_util.h>
#include <BluetoothLock.h>
#include <pico/cyw43_arch.h>

// UUIDs in the usual (big-endian, as printed) byte order; att_db_util reverses them for the wire.
static const uint8_t UUID_SVC[16] = {0xac, 0x74, 0x00, 0x01, 0x3c, 0x66, 0xcc, 0x47, 0x62, 0x90, 0xe0, 0xe7, 0x09, 0x4c, 0x17, 0xb9};
static const uint8_t UUID_EVENT[16] = {0xac, 0x74, 0x00, 0x02, 0x3c, 0x66, 0xcc, 0x47, 0x62, 0x90, 0xe0, 0xe7, 0x09, 0x4c, 0x17, 0xb9};
static const uint8_t UUID_CONFIG[16] = {0xac, 0x74, 0x00, 0x03, 0x3c, 0x66, 0xcc, 0x47, 0x62, 0x90, 0xe0, 0xe7, 0x09, 0x4c, 0x17, 0xb9};
static const uint8_t UUID_INFO[16] = {0xac, 0x74, 0x00, 0x04, 0x3c, 0x66, 0xcc, 0x47, 0x62, 0x90, 0xe0, 0xe7, 0x09, 0x4c, 0x17, 0xb9};

#if VOX_INSECURE
#define SEC_LINK ATT_SECURITY_NONE
#else
#define SEC_LINK ATT_SECURITY_ENCRYPTED
#endif

static btstack_packet_callback_registration_t s_hci_reg, s_sm_reg;
static btstack_context_callback_registration_t s_send_reg;

static uint16_t h_name, h_event, h_event_cccd, h_config, h_info;

// ---- connection state (BT context; loop reads under BluetoothLock) ----
static hci_con_handle_t s_con = HCI_CON_HANDLE_INVALID;
static bool s_up, s_notify, s_encrypted, s_send_pending;
static bool s_powered;              // the radio chip (CYW43) and BTstack are running. Only loop() changes it
static bool s_pair_window;          // new pairing requests are accepted (PROTOCOL.md "Pairing")
static uint16_t s_mtu = ATT_DEFAULT_MTU, s_max_mtu = BLE_MAX_MTU, s_interval;
static uint8_t s_key_size;
static volatile uint8_t s_hci_state = HCI_STATE_OFF;   // last BTSTACK_EVENT_STATE
static uint8_t s_frag_ctr;          // 6-bit fragment counter, restarts at 0 on every connection
static uint32_t s_sent_msgs, s_sent_frags, s_dropped;
static bd_addr_t s_addr;
static char s_name[12] = "VOX-????";
static uint8_t s_adv[31], s_adv_len, s_scan_rsp[12], s_scan_rsp_len;

// ---- TX queue of whole messages ----
static char q_buf[BLE_TX_SLOTS][BLE_MSG_MAX];
static uint16_t q_len[BLE_TX_SLOTS];
static uint8_t q_head, q_count;
static uint16_t q_off;               // bytes of the head message already notified
static uint8_t s_frag[BLE_MAX_MTU];

// ---- INFO and CONFIG ----
static char s_info[200];
static uint16_t s_info_len;
#define CFG_MAX 512
static uint8_t s_prep[CFG_MAX];      // prepared (long) write in progress
static uint16_t s_prep_len;
static char s_cfg[CFG_MAX + 1];      // last complete CONFIG value, handed to loop()
static uint16_t s_cfg_len;

// ---- deferred work for loop() ----
static volatile bool ev_ready, ev_disc, ev_cfg, ev_bonded;

// ---- log ring: BT callbacks never print ----
#define LOG_N 32
#define LOG_W 120
static char s_log[LOG_N][LOG_W];
static uint8_t s_log_head, s_log_count;
static uint32_t s_log_lost;

static void blog(const char *fmt, ...) {
    if (s_log_count == LOG_N) {
        s_log_lost++;
        return;
    }
    char *dst = s_log[(s_log_head + s_log_count) % LOG_N];
    int n = snprintf(dst, LOG_W, "[ble %lu] ", (unsigned long)millis());
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(dst + n, LOG_W - n, fmt, ap);
    va_end(ap);
    s_log_count++;
}

static void q_clear() {
    q_head = q_count = 0;
    q_off = 0;
}

static bool link_ok() {
    return s_con != HCI_CON_HANDLE_INVALID && s_notify && (VOX_INSECURE || s_encrypted);
}

static void can_send_cb(void *ctx);

static void pump() {
    if (s_send_pending || q_count == 0 || !link_ok()) return;
    s_send_reg.callback = &can_send_cb;
    s_send_reg.context = nullptr;
    s_send_pending = true;
    att_server_request_to_send_notification(&s_send_reg, s_con);
}

// One fragment per call: [header][chunk]. Header (PROTOCOL.md): bit 7 = last fragment of the message,
// bit 6 = first fragment, bits 0-5 = counter mod 64 (0 for the first notification after each connection).
static void can_send_cb(void *ctx) {
    (void)ctx;
    s_send_pending = false;
    if (q_count == 0 || !link_ok()) return;
    const char *m = q_buf[q_head];
    uint16_t len = q_len[q_head];
    uint16_t mtu = att_server_get_mtu(s_con);
    uint16_t max_chunk = mtu - 3 - 1;
    uint16_t remaining = len - q_off;
    uint16_t n = remaining < max_chunk ? remaining : max_chunk;
    if (n < remaining) {
        // never cut in front of a UTF-8 continuation byte (the lines are ASCII today, but stay safe)
        while (n > 1 && ((uint8_t)m[q_off + n] & 0xC0) == 0x80) n--;
    }
    bool last = (q_off + n == len);
    bool first = (q_off == 0);
    s_frag[0] = (uint8_t)((s_frag_ctr & 0x3F) | (first ? 0x40 : 0) | (last ? 0x80 : 0));
    memcpy(s_frag + 1, m + q_off, n);
    uint8_t err = att_server_notify(s_con, h_event, s_frag, n + 1);
    if (err) {
        blog("notify failed err=%u, retrying", err);
    } else {
        s_frag_ctr = (s_frag_ctr + 1) & 0x3F;
        s_sent_frags++;
        q_off += n;
        if (last) {
            q_head = (q_head + 1) % BLE_TX_SLOTS;
            q_count--;
            q_off = 0;
            s_sent_msgs++;
        }
    }
    pump();
}

static void start_advertising() {
    gap_local_bd_addr(s_addr);
    snprintf(s_name, sizeof(s_name), "VOX-%02X%02X", s_addr[4], s_addr[5]);
    uint8_t n = strlen(s_name);
    uint8_t *p = s_adv;
    *p++ = 2; *p++ = BLUETOOTH_DATA_TYPE_FLAGS; *p++ = 0x06;  // LE general discoverable, no BR/EDR
    *p++ = 17; *p++ = BLUETOOTH_DATA_TYPE_COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS;
    for (int i = 0; i < 16; i++) *p++ = UUID_SVC[15 - i];     // little-endian on air
    *p++ = n + 1; *p++ = BLUETOOTH_DATA_TYPE_COMPLETE_LOCAL_NAME;
    memcpy(p, s_name, n); p += n;
    s_adv_len = p - s_adv;                                      // 3 + 18 + 10 = 31: exactly fits
    s_scan_rsp[0] = n + 1; s_scan_rsp[1] = BLUETOOTH_DATA_TYPE_COMPLETE_LOCAL_NAME;
    memcpy(s_scan_rsp + 2, s_name, n);
    s_scan_rsp_len = n + 2;
    bd_addr_t null_addr = {0};
    gap_advertisements_set_params(0x00A0, 0x00A0, 0 /*ADV_IND*/, 0, null_addr, 0x07, 0);  // 100 ms
    gap_advertisements_set_data(s_adv_len, s_adv);
    gap_scan_response_set_data(s_scan_rsp_len, s_scan_rsp);
    gap_advertisements_enable(1);
    s_up = true;
    blog("up: %s %s, advertising, %s build", s_name, bd_addr_to_str(s_addr), VOX_INSECURE ? "INSECURE" : "secure");
}

static void on_disconnect(uint8_t reason) {
    blog("disconnected, reason 0x%02x (sent %lu msgs / %lu frags so far)", reason, (unsigned long)s_sent_msgs,
         (unsigned long)s_sent_frags);
    s_con = HCI_CON_HANDLE_INVALID;
    s_notify = s_encrypted = s_send_pending = false;
    s_key_size = 0;
    s_mtu = ATT_DEFAULT_MTU;
    if (q_count) s_dropped += q_count;
    q_clear();
    ev_disc = true;
}

static void hci_handler(uint8_t type, uint16_t channel, uint8_t *packet, uint16_t size) {
    (void)channel; (void)size;
    if (type != HCI_EVENT_PACKET) return;
    switch (hci_event_packet_get_type(packet)) {
    case BTSTACK_EVENT_STATE:
        s_hci_state = btstack_event_state_get_state(packet);
        if (btstack_event_state_get_state(packet) == HCI_STATE_WORKING) start_advertising();
        break;
    case HCI_EVENT_META_GAP:
        if (hci_event_gap_meta_get_subevent_code(packet) == GAP_SUBEVENT_LE_CONNECTION_COMPLETE) {
            if (gap_subevent_le_connection_complete_get_status(packet) != ERROR_CODE_SUCCESS) break;
            s_con = gap_subevent_le_connection_complete_get_connection_handle(packet);
            s_interval = gap_subevent_le_connection_complete_get_conn_interval(packet);
            s_frag_ctr = 0;
            s_notify = s_encrypted = false;
            q_clear();
            bd_addr_t peer;
            gap_subevent_le_connection_complete_get_peer_address(packet, peer);
            blog("connected: peer %s, interval %u.%02u ms", bd_addr_to_str(peer), s_interval * 125 / 100,
                 s_interval * 125 % 100);
            // Ask for a short connection interval (7.5-30 ms): the phone decides, this only lowers latency.
            gap_request_connection_parameter_update(s_con, 6, 24, 0, 400);
        }
        break;
    case HCI_EVENT_LE_META:
        if (hci_event_le_meta_get_subevent_code(packet) == HCI_SUBEVENT_LE_CONNECTION_UPDATE_COMPLETE) {
            s_interval = hci_subevent_le_connection_update_complete_get_conn_interval(packet);
            blog("connection interval now %u.%02u ms", s_interval * 125 / 100, s_interval * 125 % 100);
        }
        break;
    case HCI_EVENT_DISCONNECTION_COMPLETE:
        if (hci_event_disconnection_complete_get_connection_handle(packet) == s_con)
            on_disconnect(hci_event_disconnection_complete_get_reason(packet));
        break;
    case HCI_EVENT_ENCRYPTION_CHANGE:
    case HCI_EVENT_ENCRYPTION_CHANGE_V2: {
        hci_con_handle_t h = hci_event_encryption_change_get_connection_handle(packet);
        if (h != s_con) break;
        uint8_t st = hci_event_encryption_change_get_status(packet);
        s_encrypted = st == 0 && hci_event_encryption_change_get_encryption_enabled(packet);
        s_key_size = gap_encryption_key_size(h);
        blog("encryption %s (status 0x%02x): key size %u, LE secure connections %s, bonded %s",
             s_encrypted ? "ON" : "off", st, s_key_size, gap_secure_connection(h) ? "yes" : "NO",
             gap_bonded(h) ? "yes" : "no");
        pump();
        break;
    }
    default:
        break;
    }
}

static void sm_handler(uint8_t type, uint16_t channel, uint8_t *packet, uint16_t size) {
    (void)channel; (void)size;
    if (type != HCI_EVENT_PACKET) return;
    switch (hci_event_packet_get_type(packet)) {
    // PROTOCOL.md "Pairing": new bonds only while the pairing window is open. A bonded phone does not pair again: it
    // re-encrypts with the stored keys (SM_EVENT_REENCRYPTION_*), which works at any time.
    case SM_EVENT_JUST_WORKS_REQUEST: {
        hci_con_handle_t h = sm_event_just_works_request_get_handle(packet);
        if (s_pair_window) {
            blog("pairing: Just Works request, accepting (pairing window open)");
            sm_just_works_confirm(h);
        } else {
            blog("pairing: Just Works request REJECTED: pairing window closed (hold the button 5 s to open it)");
            sm_bonding_decline(h);
        }
        break;
    }
    case SM_EVENT_NUMERIC_COMPARISON_REQUEST: {
        hci_con_handle_t h = sm_event_numeric_comparison_request_get_handle(packet);
        if (s_pair_window) {
            blog("pairing: numeric comparison request, accepting (pairing window open)");
            sm_numeric_comparison_confirm(h);
        } else {
            blog("pairing: numeric comparison request REJECTED: pairing window closed");
            sm_bonding_decline(h);
        }
        break;
    }
    case SM_EVENT_PAIRING_STARTED:
        blog("pairing started");
        break;
    case SM_EVENT_PAIRING_COMPLETE: {
        uint8_t st = sm_event_pairing_complete_get_status(packet);
        if (st == ERROR_CODE_SUCCESS) {
            blog("pairing complete: success, bonded");
            if (s_pair_window) ev_bonded = true;
        }
        else blog("pairing FAILED: status 0x%02x reason 0x%02x", st, sm_event_pairing_complete_get_reason(packet));
        break;
    }
    case SM_EVENT_REENCRYPTION_STARTED:
        blog("re-encryption with stored bond started");
        break;
    case SM_EVENT_REENCRYPTION_COMPLETE: {
        uint8_t st = sm_event_reencryption_complete_get_status(packet);
        if (st == ERROR_CODE_SUCCESS) blog("re-encryption complete");
        else blog("re-encryption FAILED 0x%02x: the phone has a bond this device lost (re-flash erases bonds). "
                  "Remove VOX from the phone's Bluetooth list and pair again", st);
        break;
    }
    default:
        break;
    }
}

static void att_handler(uint8_t type, uint16_t channel, uint8_t *packet, uint16_t size) {
    (void)channel; (void)size;
    if (type != HCI_EVENT_PACKET) return;
    switch (hci_event_packet_get_type(packet)) {
    case ATT_EVENT_CONNECTED:
        s_mtu = att_server_get_mtu(att_event_connected_get_handle(packet));
        break;
    case ATT_EVENT_MTU_EXCHANGE_COMPLETE:
        s_mtu = att_event_mtu_exchange_complete_get_MTU(packet);
        blog("MTU %u (fragment payload %u bytes)", s_mtu, s_mtu - 4);
        break;
    default:
        break;
    }
}

static uint16_t att_read_cb(hci_con_handle_t con, uint16_t handle, uint16_t offset, uint8_t *buffer, uint16_t size) {
    (void)con;
    if (handle == h_info) return att_read_callback_handle_blob((const uint8_t *)s_info, s_info_len, offset, buffer, size);
    if (handle == h_name) return att_read_callback_handle_blob((const uint8_t *)s_name, strlen(s_name), offset, buffer, size);
    if (handle == h_event_cccd) {
        uint8_t v[2] = {(uint8_t)(s_notify ? 1 : 0), 0};
        return att_read_callback_handle_blob(v, 2, offset, buffer, size);
    }
    return 0;
}

static void config_done(const uint8_t *data, uint16_t len) {
    memcpy(s_cfg, data, len);
    s_cfg[len] = 0;
    s_cfg_len = len;
    ev_cfg = true;
}

static int att_write_cb(hci_con_handle_t con, uint16_t handle, uint16_t mode, uint16_t offset, uint8_t *buffer,
                        uint16_t size) {
    (void)con;
    // Long writes (Prepare Write ... Execute Write): BTstack calls VALIDATE / EXECUTE / CANCEL with handle 0, not
    // the attribute's handle. CONFIG is the only attribute that queues prepared data (s_prep).
    switch (mode) {
    case ATT_TRANSACTION_MODE_VALIDATE:
        return 0;
    case ATT_TRANSACTION_MODE_EXECUTE:
        if (s_prep_len) config_done(s_prep, s_prep_len);
        s_prep_len = 0;
        return 0;
    case ATT_TRANSACTION_MODE_CANCEL:
        s_prep_len = 0;
        return 0;
    default:
        break;
    }
    if (handle == h_event_cccd) {
        if (mode != ATT_TRANSACTION_MODE_NONE || size < 2) return 0;
        bool en = (little_endian_read_16(buffer, 0) & GATT_CLIENT_CHARACTERISTICS_CONFIGURATION_NOTIFICATION) != 0;
        // PROTOCOL.md "State on connect": every enable (also a repeated one, e.g. a central that restores the
        // subscription itself and then subscribes again) gets the current state.
        if (en) ev_ready = true;
        s_notify = en;
        blog("EVENT notifications %s", en ? "ON" : "off");
        pump();
        return 0;
    }
    if (handle == h_config) {
        switch (mode) {
        case ATT_TRANSACTION_MODE_NONE:
            if (size > CFG_MAX) return ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH;
            config_done(buffer, size);
            return 0;
        case ATT_TRANSACTION_MODE_ACTIVE:          // one Prepare Write of a long write
            if (offset + size > CFG_MAX) return ATT_ERROR_INVALID_ATTRIBUTE_VALUE_LENGTH;
            memcpy(s_prep + offset, buffer, size);
            if (offset + size > s_prep_len) s_prep_len = offset + size;
            return 0;
        default:
            return 0;
        }
    }
    return 0;
}

// BTstack layers above HCI, the GATT database and our handlers. Runs after every power-on: the core's CYW43 init
// (cyw43_arch_init -> btstack_cyw43_init) gives a fresh HCI and run loop, and ble_power_off() de-initialised these.
static void stack_setup() {
    BluetoothLock lock;
    l2cap_init();
    l2cap_set_max_le_mtu(s_max_mtu);
    sm_init();
    sm_set_io_capabilities(IO_CAPABILITY_NO_INPUT_NO_OUTPUT);
    sm_set_authentication_requirements(SM_AUTHREQ_SECURE_CONNECTION | SM_AUTHREQ_BONDING);
#if !VOX_INSECURE
    sm_set_secure_connections_only_mode(true);     // refuse legacy pairing
#endif

    att_db_util_init();
    att_db_util_add_service_uuid16(ORG_BLUETOOTH_SERVICE_GENERIC_ACCESS);
    h_name = att_db_util_add_characteristic_uuid16(ORG_BLUETOOTH_CHARACTERISTIC_GAP_DEVICE_NAME,
                                                   ATT_PROPERTY_READ | ATT_PROPERTY_DYNAMIC, ATT_SECURITY_NONE,
                                                   ATT_SECURITY_NONE, nullptr, 0);
    att_db_util_add_service_uuid16(ORG_BLUETOOTH_SERVICE_GENERIC_ATTRIBUTE);
    att_db_util_add_service_uuid128(UUID_SVC);
    // EVENT: notify only. The write permission applies to its CCCD, so subscribing needs an encrypted link.
    h_event = att_db_util_add_characteristic_uuid128(UUID_EVENT, ATT_PROPERTY_NOTIFY | ATT_PROPERTY_DYNAMIC,
                                                     ATT_SECURITY_NONE, SEC_LINK, nullptr, 0);
    h_event_cccd = h_event + 1;
    h_config = att_db_util_add_characteristic_uuid128(UUID_CONFIG, ATT_PROPERTY_WRITE | ATT_PROPERTY_DYNAMIC,
                                                      ATT_SECURITY_NONE, SEC_LINK, nullptr, 0);
    h_info = att_db_util_add_characteristic_uuid128(UUID_INFO, ATT_PROPERTY_READ | ATT_PROPERTY_DYNAMIC,
                                                    ATT_SECURITY_NONE, ATT_SECURITY_NONE, nullptr, 0);
    att_server_init(att_db_util_get_address(), att_read_cb, att_write_cb);

    s_hci_reg.callback = &hci_handler;
    hci_add_event_handler(&s_hci_reg);
    s_sm_reg.callback = &sm_handler;
    sm_add_event_handler(&s_sm_reg);               // SM's handler list survives a power cycle: added only once
    att_server_register_packet_handler(&att_handler);
    int prc = hci_power_control(HCI_POWER_ON);
    if (prc) blog("hci_power_control(ON) returned %d", prc);
}

void ble_begin() {
    s_powered = true;     // the core powered the CYW43 up before setup()
    stack_setup();
}

bool ble_powered() { return s_powered; }

// Sleep: drop the link, stop advertising, then power the CYW43 down completely (cyw43_arch_deinit: BTstack HCI off,
// driver de-init, WL_REG_ON low). Bonds stay in flash. Returns after the chip is off.
void ble_power_off() {
    if (!s_powered) return;
    {
        BluetoothLock lock;
        s_pair_window = false;
        gap_advertisements_enable(0);
        if (s_con != HCI_CON_HANDLE_INVALID) gap_disconnect(s_con);
    }
    uint32_t t0 = millis();
    while (millis() - t0 < 1000) {
        {
            BluetoothLock lock;
            if (s_con == HCI_CON_HANDLE_INVALID) break;
        }
        delay(5);
    }
    // Halt HCI and wait until BTstack reports OFF. From WORKING, HCI_POWER_OFF only starts an asynchronous halt
    // (it still talks to the controller); tearing the chip and the run loop down during that hangs the device
    // (seen: USB dead, no recovery without a power cycle). cyw43_arch_deinit() does not wait for it by itself.
    {
        BluetoothLock lock;
        hci_power_control(HCI_POWER_OFF);
    }
    t0 = millis();
    while (s_hci_state != HCI_STATE_OFF && millis() - t0 < 2000) delay(5);
    if (s_hci_state != HCI_STATE_OFF) blog("power off: HCI did not halt within 2 s (state %u)", s_hci_state);
    {
        BluetoothLock lock;
        if (s_con != HCI_CON_HANDLE_INVALID) {
            blog("power off: the link did not close in time; powering down anyway");
            on_disconnect(0x16);
        }
        // de-initialise the layers above HCI so that stack_setup() can run again after the next power-on
        sm_deinit();
        btstack_crypto_deinit();
        att_server_deinit();
        l2cap_deinit();
        s_up = false;
    }
    s_powered = false;    // from here on nothing may take BluetoothLock: the async context is gone
    cyw43_arch_deinit();
    blog("radio off (CYW43 powered down)");
}

bool ble_power_on() {
    if (s_powered) return true;
    uint32_t t0 = millis();
    int rc = cyw43_arch_init_with_country(WIFICC);
    if (rc) {
        blog("power on FAILED: cyw43_arch_init returned %d", rc);
        return false;
    }
    s_powered = true;
    stack_setup();
    blog("radio on (CYW43 init %lu ms)", (unsigned long)(millis() - t0));
    return true;
}

void ble_set_pairing_window(bool open) {
    if (!s_powered) {
        s_pair_window = false;
        return;
    }
    BluetoothLock lock;
    s_pair_window = open;
}

bool ble_pairing_window() { return s_pair_window; }

void ble_poll() {
    char line[LOG_W];
    bool ready = false, disc = false, cfg = false, bonded = false;
    static char cfg_copy[CFG_MAX + 1];
    size_t cfg_len = 0;
    for (;;) {
        bool have = false;
        {
            // Asleep there is no BT context, so no lock (and no async context to lock).
            if (s_powered) async_context_acquire_lock_blocking(cyw43_arch_async_context());
            if (s_log_count) {
                memcpy(line, s_log[s_log_head], LOG_W);
                s_log_head = (s_log_head + 1) % LOG_N;
                s_log_count--;
                have = true;
            } else {
                ready = ev_ready; ev_ready = false;
                disc = ev_disc; ev_disc = false;
                cfg = ev_cfg; ev_cfg = false;
                bonded = ev_bonded; ev_bonded = false;
                if (cfg) {
                    memcpy(cfg_copy, s_cfg, s_cfg_len + 1);
                    cfg_len = s_cfg_len;
                }
            }
            if (s_powered) async_context_release_lock(cyw43_arch_async_context());
        }
        if (!have) break;
        out_line(line);
    }
    if (disc) on_ble_disconnected();
    if (bonded) on_ble_bonded();
    if (ready) on_ble_ready();
    if (cfg) on_ble_config(cfg_copy, cfg_len);
}

bool ble_ready() {
    if (!s_powered) return false;
    BluetoothLock lock;
    return link_ok();
}

bool ble_connected() {
    if (!s_powered) return false;
    BluetoothLock lock;
    return s_con != HCI_CON_HANDLE_INVALID;
}

bool ble_tx_idle() {
    if (!s_powered) return true;
    BluetoothLock lock;
    return q_count == 0 && !s_send_pending;
}

bool ble_send(const char *msg, size_t len) {
    if (!s_powered) return false;
    BluetoothLock lock;
    if (!link_ok()) return false;
    if (len == 0 || len > BLE_MSG_MAX || q_count == BLE_TX_SLOTS) {
        s_dropped++;
        return false;
    }
    uint8_t slot = (q_head + q_count) % BLE_TX_SLOTS;
    memcpy(q_buf[slot], msg, len);
    q_len[slot] = len;
    q_count++;
    pump();
    return true;
}

void ble_set_info(const char *json) {
    if (s_powered) async_context_acquire_lock_blocking(cyw43_arch_async_context());
    strncpy(s_info, json, sizeof(s_info) - 1);
    s_info[sizeof(s_info) - 1] = 0;
    s_info_len = strlen(s_info);
    if (s_powered) async_context_release_lock(cyw43_arch_async_context());
}

static int bond_count_locked() {
    int n = 0;
    for (int i = 0; i < le_device_db_max_count(); i++) {
        int addr_type = BD_ADDR_TYPE_UNKNOWN;
        bd_addr_t a;
        sm_key_t irk;
        le_device_db_info(i, &addr_type, a, irk);
        if (addr_type != BD_ADDR_TYPE_UNKNOWN) n++;
    }
    return n;
}

void ble_status(BleStatus *st) {
    memset(st, 0, sizeof(*st));
    st->powered = s_powered;
    st->pair_window = s_pair_window;
    st->max_mtu = s_max_mtu;
    st->sent_msgs = s_sent_msgs;
    st->sent_frags = s_sent_frags;
    st->dropped_msgs = s_dropped;
    strncpy(st->name, s_name, sizeof(st->name));
    st->bonds = -1;
    if (!s_powered) return;
    BluetoothLock lock;
    st->up = s_up;
    st->connected = s_con != HCI_CON_HANDLE_INVALID;
    st->encrypted = s_encrypted;
    st->secure_conn = st->connected && gap_secure_connection(s_con);
    st->bonded = st->connected && gap_bonded(s_con);
    st->notify = s_notify;
    st->mtu = s_mtu;
    st->conn_interval_x125 = s_interval;
    st->key_size = s_key_size;
    st->queued = q_count;
    st->bonds = bond_count_locked();
    strncpy(st->addr, bd_addr_to_str(s_addr), sizeof(st->addr));
}

void ble_set_max_mtu(uint16_t mtu) {
    s_max_mtu = mtu;
    if (!s_powered) return;
    BluetoothLock lock;
    l2cap_set_max_le_mtu(mtu);
}

void ble_disconnect() {
    if (!s_powered) return;
    BluetoothLock lock;
    if (s_con != HCI_CON_HANDLE_INVALID) gap_disconnect(s_con);
}

int ble_forget_bonds() {
    if (!s_powered) return -1;
    BluetoothLock lock;
    int n = 0;
    for (int i = 0; i < le_device_db_max_count(); i++) {
        int addr_type = BD_ADDR_TYPE_UNKNOWN;
        bd_addr_t a;
        sm_key_t irk;
        le_device_db_info(i, &addr_type, a, irk);
        if (addr_type != BD_ADDR_TYPE_UNKNOWN) {
            le_device_db_remove(i);
            n++;
        }
    }
    return n;
}
