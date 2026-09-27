#include "vx_impl.h"
#include "vx_config.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

void vx_config_default(VxConfig *c) {
#define VX_DEF_I(n, d) c->n = d;
#define VX_DEF_R(n, d) c->n = d;
#define VX_DEF_O(n) c->has_##n = false; c->n = 0.0;
    VX_CONFIG_FIELDS(VX_DEF_I, VX_DEF_R, VX_DEF_O)
#undef VX_DEF_I
#undef VX_DEF_R
#undef VX_DEF_O
}

static bool pow2(int n) { return n > 0 && (n & (n - 1)) == 0; }

const char *vx_config_check(const VxConfig *c) {
    if (c->sample_rate != 16000) return "sample_rate must be 16000";
    if (!pow2(c->win) || c->win > VX_MAX_WIN || c->win < 64) return "win must be a power of two <= 512";
    if (!pow2(c->acf_fft) || c->acf_fft > VX_MAX_ACF || c->acf_fft < c->win) return "acf_fft must be a power of two, win..1024";
    if (c->hop < 1 || c->hop > VX_MAX_HOP || c->hop > c->win) return "hop out of range";
    if (c->max_segment_frames < 1 || c->max_segment_frames > VX_MAX_SEG) return "max_segment_frames > 400";
    if (c->hangover_frames < 1 || c->hangover_frames > VX_MAX_HANG) return "hangover_frames out of range";
    if (c->open_frames < 1 || c->open_frames > VX_MAX_OPEN) return "open_frames out of range";
    if (c->floor_blocks < 1 || c->floor_blocks > VX_MAX_BLOCKS) return "floor_blocks out of range";
    if (c->floor_block_frames < 1 || c->floor_startup_sub_frames < 1 ||
        c->floor_block_frames / c->floor_startup_sub_frames + 1 > VX_MAX_SUB) return "floor sub-blocks out of range";
    if (c->median_frames < 1 || c->smooth_frames < 1 || c->edge_frames < 1) return "filter lengths must be >= 1";
    return NULL;
}

// ---- setting fields by name (JSON loading) ----
enum { VX_T_INT, VX_T_REAL, VX_T_OPT };
struct VxField { const char *name; int type; size_t off; size_t off_has; };

static const VxField FIELDS[] = {
#define VX_F_I(n, d) {#n, VX_T_INT, offsetof(VxConfig, n), 0},
#define VX_F_R(n, d) {#n, VX_T_REAL, offsetof(VxConfig, n), 0},
#define VX_F_O(n) {#n, VX_T_OPT, offsetof(VxConfig, n), offsetof(VxConfig, has_##n)},
    VX_CONFIG_FIELDS(VX_F_I, VX_F_R, VX_F_O)
#undef VX_F_I
#undef VX_F_R
#undef VX_F_O
};
static const int N_FIELDS = sizeof(FIELDS) / sizeof(FIELDS[0]);

bool vx_config_set(VxConfig *c, const char *key, const char *value) {
    for (int i = 0; i < N_FIELDS; i++) {
        const VxField &f = FIELDS[i];
        if (strcmp(f.name, key)) continue;
        char *base = (char *)c;
        if (!strcmp(value, "null")) {
            if (f.type != VX_T_OPT) return false;
            *(bool *)(base + f.off_has) = false;
            *(double *)(base + f.off) = 0.0;
            return true;
        }
        char *end;
        double v = strtod(value, &end);
        if (end == value || *end) return false;
        if (f.type == VX_T_INT) {
            if (v != (double)(int)v) return false;   // Python would keep a float; the C struct cannot
            *(int *)(base + f.off) = (int)v;
        } else {
            *(double *)(base + f.off) = v;
            if (f.type == VX_T_OPT) *(bool *)(base + f.off_has) = true;
        }
        return true;
    }
    return false;
}

const char *vx_config_load_json(VxConfig *c, const char *s) {
    static char err[128];
    const char *p = s;
    while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
    if (*p++ != '{') return "config: not a JSON object";
    for (;;) {
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n' || *p == ',') p++;
        if (*p == '}') return NULL;
        if (*p != '"') return "config: expected a key";
        const char *k0 = ++p;
        while (*p && *p != '"') p++;
        if (!*p) return "config: unterminated key";
        char key[64];
        size_t kl = (size_t)(p - k0);
        if (kl >= sizeof(key)) return "config: key too long";
        memcpy(key, k0, kl);
        key[kl] = 0;
        p++;
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        if (*p++ != ':') return "config: expected ':'";
        while (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n') p++;
        const char *v0 = p;
        while (*p && *p != ',' && *p != '}' && *p != ' ' && *p != '\r' && *p != '\n') p++;
        char val[48];
        size_t vl = (size_t)(p - v0);
        if (!vl || vl >= sizeof(val)) return "config: bad value";
        memcpy(val, v0, vl);
        val[vl] = 0;
        if (!vx_config_set(c, key, val)) {
            snprintf(err, sizeof(err), "config: unknown key or bad value: %s", key);
            return err;
        }
    }
}

size_t vx_config_json(const VxConfig *c, char *out, size_t cap) {
    size_t n = 0;
#define VX_APPEND(...)                                                            \
    do {                                                                          \
        int w = snprintf(out + (n < cap ? n : cap), n < cap ? cap - n : 0, __VA_ARGS__); \
        if (w > 0) n += (size_t)w;                                                \
    } while (0)
    VX_APPEND("{");
    for (int i = 0; i < N_FIELDS; i++) {
        const VxField &f = FIELDS[i];
        const char *base = (const char *)c;
        VX_APPEND("%s\"%s\": ", i ? ", " : "", f.name);
        if (f.type == VX_T_INT) VX_APPEND("%d", *(const int *)(base + f.off));
        else if (f.type == VX_T_OPT && !*(const bool *)(base + f.off_has)) VX_APPEND("null");
        else VX_APPEND("%.17g", *(const double *)(base + f.off));
    }
    VX_APPEND("}");
#undef VX_APPEND
    return n;
}
