#include "vx_impl.h"
#include "vx_vocab.h"
#include <stdio.h>

const char *const VX_CONTOUR_KEYS[VX_N_CONTOURS] = {"rise", "fall", "arch", "dip", "flat"};
const char *const VX_CONTOURS[VX_N_CONTOURS] = {"rises from low to high", "falls from high to low", "rises then falls",
                                                "falls then rises", "stays level"};
const char *const VX_DISCRETE_KEYS[VX_N_DISCRETE] = {"pop", "click", "hiss"};
const char *const VX_DISCRETE[VX_N_DISCRETE] = {"a short lip pop", "a tongue click", "a hiss"};
const char *const VX_EXCURSION[3] = {"small (under 2 semitones)", "medium (2-4 semitones)", "large (over 4 semitones)"};
const char *const VX_DURATION[4] = {"very short (under 150 ms)", "short (150-400 ms)", "medium (400-1000 ms)",
                                    "long (over 1 s)"};
const char *const VX_CLARITY[3] = {"noisy", "breathy", "clear tone"};
const char *const VX_LOUDNESS[3] = {"quiet", "normal", "loud"};
const char *const VX_SOUNDS_LIKE[VX_N_LIKE] = {"hum", "whistle", "talking", "laughing", "coughing",
                                               "background music", "background noise", "mouth sound"};

static size_t put(char *out, size_t cap, size_t n, const char *s) {
    int w = snprintf(out + (n < cap ? n : cap), n < cap ? cap - n : 0, "%s", s);
    return n + (w > 0 ? (size_t)w : 0);
}

static size_t list(char *out, size_t cap, size_t n, const char *const *v, int k) {
    n = put(out, cap, n, "[");
    for (int i = 0; i < k; i++) {
        if (i) n = put(out, cap, n, ", ");
        n = put(out, cap, n, "\"");
        n = put(out, cap, n, v[i]);
        n = put(out, cap, n, "\"");
    }
    return put(out, cap, n, "]");
}

// dict with its keys sorted (sort_keys=True)
static size_t dict(char *out, size_t cap, size_t n, const char *const *keys, const char *const *vals, int k) {
    int order[8];
    for (int i = 0; i < k; i++) order[i] = i;
    for (int i = 1; i < k; i++)
        for (int j = i; j > 0; j--) {
            const char *a = keys[order[j - 1]], *b = keys[order[j]];
            int c = 0;
            while (*a && *a == *b) a++, b++;
            c = (unsigned char)*a - (unsigned char)*b;
            if (c > 0) {
                int t = order[j];
                order[j] = order[j - 1];
                order[j - 1] = t;
            }
        }
    n = put(out, cap, n, "{");
    for (int i = 0; i < k; i++) {
        if (i) n = put(out, cap, n, ", ");
        n = put(out, cap, n, "\"");
        n = put(out, cap, n, keys[order[i]]);
        n = put(out, cap, n, "\": \"");
        n = put(out, cap, n, vals[order[i]]);
        n = put(out, cap, n, "\"");
    }
    return put(out, cap, n, "}");
}

size_t vx_vocab_json(char *out, size_t cap) {
    size_t n = 0;
    n = put(out, cap, n, "{\"CLARITY\": ");
    n = list(out, cap, n, VX_CLARITY, 3);
    n = put(out, cap, n, ", \"CONTOURS\": ");
    n = dict(out, cap, n, VX_CONTOUR_KEYS, VX_CONTOURS, VX_N_CONTOURS);
    n = put(out, cap, n, ", \"DISCRETE\": ");
    n = dict(out, cap, n, VX_DISCRETE_KEYS, VX_DISCRETE, VX_N_DISCRETE);
    n = put(out, cap, n, ", \"DURATION\": ");
    n = list(out, cap, n, VX_DURATION, 4);
    n = put(out, cap, n, ", \"EXCURSION\": ");
    n = list(out, cap, n, VX_EXCURSION, 3);
    n = put(out, cap, n, ", \"LOUDNESS\": ");
    n = list(out, cap, n, VX_LOUDNESS, 3);
    n = put(out, cap, n, ", \"SOUNDS_LIKE\": ");
    n = list(out, cap, n, VX_SOUNDS_LIKE, VX_N_LIKE);
    return put(out, cap, n, "}");
}
