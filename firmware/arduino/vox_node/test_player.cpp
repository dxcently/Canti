#include "test_player.h"
#include "out.h"
#include "test_sounds.h"
#include "vox_state.h"

struct Pending {
    int sound;
    uint32_t t_start, t_end;   // device clock; the message goes out at t_end
};
static Pending s_q[3];
static int s_n = 0, s_i = 0;
static int s_cycle = 0;

static int find_sound(const char *name) {
    for (int i = 0; i < VOX_N_TEST_SOUNDS; i++)
        if (!strcmp(VOX_TEST_SOUNDS[i].name, name)) return i;
    return -1;
}

static int find_seq(const char *name) {
    for (int i = 0; i < VOX_N_TEST_SEQS; i++)
        if (!strcmp(VOX_TEST_SEQS[i].name, name)) return i;
    return -1;
}

bool player_busy() { return s_i < s_n; }

void player_cancel() {
    if (player_busy()) out_printf("test sequence cancelled (%d of %d sent)", s_i, s_n);
    s_n = s_i = 0;
}

static bool start(const int *sounds, const int *gaps, int n) {
    if (player_busy()) {
        out_line("err: a test sequence is still running");
        return false;
    }
    uint32_t now = millis();
    uint32_t end = now;
    for (int k = 0; k < n; k++) {
        const VoxTestSound &s = VOX_TEST_SOUNDS[sounds[k]];
        uint32_t start = k == 0 ? (end >= s.dur_ms ? end - s.dur_ms : 0) : end + gaps[k - 1];
        if (k > 0) end = start + s.dur_ms;
        s_q[k] = {sounds[k], start, end};
    }
    s_n = n;
    s_i = 0;
    player_poll(now);
    return true;
}

static bool start_seq_index(int q) {
    const VoxTestSeq &sq = VOX_TEST_SEQS[q];
    int sounds[3], gaps[2];
    for (int k = 0; k < sq.n; k++) sounds[k] = sq.sound[k];
    for (int k = 0; k + 1 < sq.n; k++) gaps[k] = sq.gap_ms[k];
    out_printf("sequence %s: %d sounds", sq.name, sq.n);
    return start(sounds, gaps, sq.n);
}

bool player_send(const char *name) {
    int i = find_sound(name);
    if (i >= 0) {
        int gaps[1] = {0};
        return start(&i, gaps, 1);
    }
    int q = find_seq(name);
    if (q >= 0) return start_seq_index(q);
    out_printf("err: unknown sound '%s' (try `list`)", name);
    return false;
}

bool player_seq(const char *const *names, int n, int gap_ms) {
    if (n == 1) {
        int q = find_seq(names[0]);
        if (q >= 0) return start_seq_index(q);
    }
    if (n < 1 || n > 3) {
        out_line("err: seq takes 1-3 sounds");
        return false;
    }
    int sounds[3], gaps[2];
    for (int k = 0; k < n; k++) {
        sounds[k] = find_sound(names[k]);
        if (sounds[k] < 0) {
            out_printf("err: unknown sound '%s' (try `list`)", names[k]);
            return false;
        }
        if (k < 2) gaps[k] = gap_ms < 0 ? 250 : gap_ms;
    }
    return start(sounds, gaps, n);
}

void player_poll(uint32_t now) {
    while (s_i < s_n && (int32_t)(now - s_q[s_i].t_end) >= 0) {
        const Pending &p = s_q[s_i++];
        const VoxTestSound &s = VOX_TEST_SOUNDS[p.sound];
        send_sound(s.label, s.line, p.t_start, p.t_end);
    }
}

void player_next_in_cycle() {
    // the 8 single sounds (not the clickpop.N parts), then the sequences
    static const char *const order[] = {"rise", "fall", "arch", "dip", "flat", "pop", "click", "hiss"};
    const int n_single = sizeof(order) / sizeof(order[0]);
    int total = n_single + VOX_N_TEST_SEQS;
    int k = s_cycle % total;
    s_cycle++;
    if (k < n_single) {
        out_printf("button test sound %d/%d: %s", k + 1, total, order[k]);
        player_send(order[k]);
    } else {
        out_printf("button test sound %d/%d: sequence %s", k + 1, total, VOX_TEST_SEQS[k - n_single].name);
        start_seq_index(k - n_single);
    }
}

void player_list() {
    out_printf("canned sounds (from the Python extractor, digest %s, vocab %s):", VOX_TEST_SOUNDS_DIGEST,
               VOX_VOCAB_DIGEST);
    for (int i = 0; i < VOX_N_TEST_SOUNDS; i++)
        out_printf("  %-11s %-5s %4u ms  %s", VOX_TEST_SOUNDS[i].name, VOX_TEST_SOUNDS[i].label,
                   VOX_TEST_SOUNDS[i].dur_ms, VOX_TEST_SOUNDS[i].line);
    out_line("sequences (each sound in its own message, timed on the device clock):");
    for (int i = 0; i < VOX_N_TEST_SEQS; i++) {
        const VoxTestSeq &q = VOX_TEST_SEQS[i];
        char buf[96];
        int n = snprintf(buf, sizeof(buf), "  %-9s", q.name);
        for (int k = 0; k < q.n; k++) {
            if (k) n += snprintf(buf + n, sizeof(buf) - n, " +%ums", q.gap_ms[k - 1]);
            n += snprintf(buf + n, sizeof(buf) - n, " %s", VOX_TEST_SOUNDS[q.sound[k]].label);
        }
        out_line(buf);
    }
}
