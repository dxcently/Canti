#include "vx_impl.h"
#include "vx_lines.h"
#include <stdio.h>
#include "vx_vocab.h"

size_t vx_hum_line(char *out, int contour, int excursion, int duration, int tone, int loudness, int like) {
    return (size_t)snprintf(out, VX_LINE_MAX,
                            "hum that %s; pitch change %s; duration %s; tone %s; loudness %s; sounds like %s",
                            VX_CONTOURS[contour], VX_EXCURSION[excursion], VX_DURATION[duration], VX_CLARITY[tone],
                            VX_LOUDNESS[loudness], VX_SOUNDS_LIKE[like]);
}

size_t vx_hiss_line(char *out, int duration, int loudness, int like) {
    return (size_t)snprintf(out, VX_LINE_MAX, "%s; duration %s; loudness %s; sounds like %s", VX_DISCRETE[VX_HISS],
                            VX_DURATION[duration], VX_LOUDNESS[loudness], VX_SOUNDS_LIKE[like]);
}

size_t vx_discrete_line(char *out, int kind, int loudness) {
    return (size_t)snprintf(out, VX_LINE_MAX, "%s; instant sound; loudness %s; sounds like mouth sound",
                            VX_DISCRETE[kind], VX_LOUDNESS[loudness]);
}
