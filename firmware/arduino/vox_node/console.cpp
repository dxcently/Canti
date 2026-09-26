#include "console.h"
#include "ble_link.h"
#include "config.h"
#include "controls.h"
#include "mic.h"
#include "out.h"
#include "power.h"
#include "status_led.h"
#include "test_player.h"
#include "vox_state.h"

static char s_line[160];
static size_t s_len;

void console_help() {
    static const char *const lines[] = {
        "VOX node commands:",
        "  status                   state, power, BLE link, mic, versions",
        "  arm | pause | stop       change the armed state (each sends a no-sound message)",
        "  mode gesture|cursor      set the mode (`mode` alone toggles)",
        "  btn click                press the button once (through the real button logic: acts after the 400 ms gap)",
        "  btn clicks <n>           n quick presses, e.g. `btn clicks 5` (arm / sleep / wake)",
        "  btn hold <ms>            hold the button, e.g. `btn hold 1200` (stop, sleep on release),",
        "                           `btn hold 5500` (pairing window)",
        "  sleep | wake             sleep now (like CONFIG sleep) | wake without arming (test helper)",
        "  buttons                  the real button's level and the button state machine (wiring test)",
        "  list                     the canned sounds and sequences",
        "  send <sound>             send one canned sound, e.g. `send rise` (or a sequence name)",
        "  seq <a> <b> [<c>] [gap]  send sounds as separate messages, `gap` ms apart on the device clock (250)",
        "  seq clickpop|poppop|riserise   the canned sequences",
        "  pad <bytes>              send a state message padded with JSON whitespace (fragmentation test)",
        "  test on|off              2 presses of the button send the next canned sound",
        "  mic level|stream|off     mic diagnostics (stream = binary frames; use tools/pico_stream.py)",
        "  mic gain <0|6|12|18|24>  stream gain in dB",
        "  ble                      link details",
        "  ble mtu <23..517>        largest MTU accepted on the NEXT connection",
        "  ble disconnect | ble forget   drop the link | erase all stored bonds",
        "  led on|off|auto          force the blue Bluetooth LED on/off (wiring test) | back to status",
        "  reboot | bootsel         restart | restart into the USB bootloader",
    };
    for (auto l : lines) out_line(l);
}

void print_status() {
    BleStatus b;
    ble_status(&b);
    out_printf("vox_node %s (%s build), up %lu ms", VOX_FW_VERSION, VOX_INSECURE ? "INSECURE debug" : "secure",
               (unsigned long)millis());
    out_printf("state: %s, %s mode, test-sound trigger %s, last id %lu",
               g_state.armed ? "armed" : (g_state.stopped ? "stopped" : "paused"), mode_name(g_state.mode),
               g_state.test_sounds ? "on" : "off", (unsigned long)last_msg_id());
    power_status();
    if (!b.powered) {
        out_printf("ble: %s, radio off (asleep)", b.name);
    } else if (!b.connected) {
        out_printf("ble: %s %s, %s, %d bond(s), pairing window %s", b.name, b.addr,
                   b.up ? "advertising, not connected" : "starting", b.bonds, b.pair_window ? "OPEN" : "closed");
    } else {
        out_printf("ble: %s connected, MTU %u, interval %u.%02u ms, encrypted %s (key %u, LESC %s, bonded %s), "
                   "notify %s, %d bond(s), pairing window %s",
                   b.name, b.mtu, b.conn_interval_x125 * 125 / 100, b.conn_interval_x125 * 125 % 100,
                   b.encrypted ? "yes" : "no", b.key_size, b.secure_conn ? "yes" : "no", b.bonded ? "yes" : "no",
                   b.notify ? "on" : "off", b.bonds, b.pair_window ? "OPEN" : "closed");
    }
    out_printf("ble: sent %lu msgs in %lu fragments, dropped %lu, queued %u, next-connection max MTU %u",
               (unsigned long)b.sent_msgs, (unsigned long)b.sent_frags, (unsigned long)b.dropped_msgs, b.queued,
               b.max_mtu);
    mic_status();
}

static int split(char *s, char **argv, int max) {
    int n = 0;
    while (*s && n < max) {
        while (*s == ' ' || *s == '\t') *s++ = 0;
        if (!*s) break;
        argv[n++] = s;
        while (*s && *s != ' ' && *s != '\t') s++;
    }
    return n;
}

static bool is_number(const char *s) {
    if (!*s) return false;
    for (; *s; s++)
        if (*s < '0' || *s > '9') return false;
    return true;
}

static void run(char *line) {
    char *argv[8];
    int argc = split(line, argv, 8);
    if (!argc) return;
    const char *c = argv[0];
    if (!strcmp(c, "help") || !strcmp(c, "?")) {
        console_help();
    } else if (!strcmp(c, "status")) {
        print_status();
    } else if (!strcmp(c, "arm")) {
        if (power_asleep()) out_line("err: asleep (`btn clicks 5` wakes it and arms on connect)");
        else state_arm("serial");
    } else if (!strcmp(c, "pause")) {
        power_disarmed();
        state_pause("serial");
    } else if (!strcmp(c, "stop")) {
        player_cancel();
        power_disarmed();
        state_stop("serial");
    } else if (!strcmp(c, "mode")) {
        if (argc < 2) state_toggle_mode("serial");
        else if (!strcmp(argv[1], "gesture")) state_set_mode(VoxMode::Gesture, "serial");
        else if (!strcmp(argv[1], "cursor")) state_set_mode(VoxMode::Cursor, "serial");
        else out_line("err: mode gesture|cursor");
    } else if (!strcmp(c, "sleep")) {
        power_sleep("serial");
    } else if (!strcmp(c, "wake")) {
        if (!power_asleep()) out_line("already awake");
        else power_wake_plain("serial");
    } else if (!strcmp(c, "btn")) {
        bool ok = true, busy = false;
        if (argc == 2 && !strcmp(argv[1], "click")) busy = !controls_sim_clicks(1);
        else if (argc == 3 && !strcmp(argv[1], "clicks") && is_number(argv[2]) && atoi(argv[2]) >= 1 && atoi(argv[2]) <= 12)
            busy = !controls_sim_clicks(atoi(argv[2]));
        else if (argc == 3 && !strcmp(argv[1], "hold") && is_number(argv[2]) && atol(argv[2]) <= 30000)
            busy = !controls_sim_hold(atol(argv[2]));
        else ok = false;
        if (!ok) out_line("err: btn click | btn clicks <1..12> | btn hold <ms, up to 30000>");
        else if (busy) out_line("err: btn: the previous simulated presses are still running");
        else out_line("btn: simulating");
    } else if (!strcmp(c, "list")) {
        player_list();
    } else if (!strcmp(c, "send")) {
        if (argc != 2) out_line("err: send <sound>");
        else player_send(argv[1]);
    } else if (!strcmp(c, "seq")) {
        int gap = -1, n = argc - 1;
        if (n >= 2 && is_number(argv[argc - 1])) {
            gap = atoi(argv[argc - 1]);
            n--;
        }
        if (n < 1) out_line("err: seq <a> <b> [<c>] [gap_ms]");
        else player_seq(argv + 1, n, gap);
    } else if (!strcmp(c, "pad")) {
        if (argc != 2 || !is_number(argv[1])) out_line("err: pad <bytes>");
        else send_padded_state(atoi(argv[1]));
    } else if (!strcmp(c, "test")) {
        if (argc == 2 && !strcmp(argv[1], "on")) state_set_test_sounds(true, "serial");
        else if (argc == 2 && !strcmp(argv[1], "off")) state_set_test_sounds(false, "serial");
        else out_line("err: test on|off");
    } else if (!strcmp(c, "mic")) {
        if (power_asleep() && argc >= 2 && strcmp(argv[1], "off") && strcmp(argv[1], "gain")) {
            out_line("err: asleep, the mic is off");
        } else if (argc >= 2 && !strcmp(argv[1], "level")) mic_set_mode(MicMode::Level);
        else if (argc >= 2 && !strcmp(argv[1], "stream")) mic_set_mode(MicMode::Stream);
        else if (argc >= 2 && !strcmp(argv[1], "off")) mic_set_mode(MicMode::Off);
        else if (argc == 3 && !strcmp(argv[1], "gain") && is_number(argv[2])) {
            mic_set_gain_db(atoi(argv[2]));
            out_printf("mic stream gain %d dB", mic_gain_db());
        } else mic_status();
    } else if (!strcmp(c, "ble")) {
        if (argc == 1) {
            print_status();
        } else if (!strcmp(argv[1], "mtu") && argc == 3 && is_number(argv[2])) {
            int m = constrain(atoi(argv[2]), 23, BLE_MAX_MTU);
            ble_set_max_mtu(m);
            out_printf("max MTU %d from the next connection (`ble disconnect` to apply now)", m);
        } else if (!strcmp(argv[1], "disconnect")) {
            ble_disconnect();
            out_line("disconnecting");
        } else if (!strcmp(argv[1], "forget")) {
            int n = ble_forget_bonds();
            if (n < 0) out_line("err: asleep, the radio is off (wake it first)");
            else out_printf("erased %d stored bond(s); also remove VOX from the phone/PC Bluetooth list", n);
        } else {
            out_line("err: ble [mtu N | disconnect | forget]");
        }
    } else if (!strcmp(c, "led")) {
        if (argc == 2 && !strcmp(argv[1], "on")) led_set_override(1);
        else if (argc == 2 && !strcmp(argv[1], "off")) led_set_override(0);
        else if (argc == 2 && !strcmp(argv[1], "auto")) led_set_override(-1);
        else out_line("err: led on|off|auto");
    } else if (!strcmp(c, "buttons")) {
        out_line(controls_state());
    } else if (!strcmp(c, "reboot")) {
        out_line("rebooting");
        Serial.flush();
        delay(50);
        rp2040.reboot();
    } else if (!strcmp(c, "bootsel")) {
        out_line("rebooting into BOOTSEL (USB drive RP2350)");
        Serial.flush();
        delay(50);
        rp2040.rebootToBootloader();
    } else {
        out_printf("err: unknown command '%s' (try `help`)", c);
    }
}

void console_poll() {
    while (Serial.available()) {
        int ch = Serial.read();
        if (ch < 0) break;
        if (ch == '\r' || ch == '\n') {
            if (s_len) {
                s_line[s_len] = 0;
                if (!g_streaming) out_printf("> %s", s_line);
                run(s_line);
                s_len = 0;
            }
        } else if (s_len < sizeof(s_line) - 1) {
            s_line[s_len++] = (char)ch;
        }
    }
}
