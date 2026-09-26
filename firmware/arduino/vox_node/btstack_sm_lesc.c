// BTstack Security Manager rebuilt WITH LE Secure Connections.
//
// Why: arduino-pico 6.1.1 ships BTstack prebuilt (lib/rp2350/liblwip-bt.a) from an include/btstack_config.h that
// defines ENABLE_MICRO_ECC_FOR_LE_SECURE_CONNECTIONS but not ENABLE_LE_SECURE_CONNECTIONS. Its sm.o therefore only
// does legacy pairing, and sm_set_secure_connections_only_mode(true) is a silent no-op. Measured on the device:
// BlueZ paired, but gap_secure_connection() said NO. PROTOCOL.md requires LE Secure Connections bonding.
//
// How: compile the core's own sm.c (same BTstack version as the library) here with the flag set. Objects in the
// sketch are linked before the archives, so the archive's sm.o is never pulled in. If a symbol were missing here,
// the linker would pull the archive member and fail with duplicate definitions, so it cannot silently mix.
// Nothing else in the library depends on this flag in a way that matters here: ECC P-256 (micro-ecc) is already
// compiled into btstack_crypto via ENABLE_MICRO_ECC_FOR_LE_SECURE_CONNECTIONS; hci.h/hci_cmd.c only use it for
// controller-side ECC commands, which are not used with micro-ecc; no shared struct changes layout.
//
// Tied to the pinned core version: when updating arduino-pico, check that the new include/btstack_config.h still
// lacks the flag (then keep this file) or has it (then delete this file).

#if defined(ENABLE_BLE)
#define ENABLE_LE_SECURE_CONNECTIONS
#include "ble/sm.c"
#endif
