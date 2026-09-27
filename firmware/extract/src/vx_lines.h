// Sound lines, byte for byte as extractor/vox_extract/lines.py (= finetune/vox/generate.py):
//   hum:       "hum that <contour>; pitch change <exc>; duration <dur>; tone <tone>; loudness <loud>; sounds like <like>"
//   hiss:      "a hiss; duration <dur>; loudness <loud>; sounds like <like>"
//   pop/click: "<a short lip pop|a tongue click>; instant sound; loudness <loud>; sounds like mouth sound"
// Every argument is an index into the vx_vocab.h tables, so a line cannot leave the vocabulary.
// The longest line is 177 bytes; VX_LINE_MAX leaves room.
#pragma once
#include <stddef.h>

#define VX_LINE_MAX 200

size_t vx_hum_line(char *out, int contour, int excursion, int duration, int tone, int loudness, int like);
size_t vx_hiss_line(char *out, int duration, int loudness, int like);
size_t vx_discrete_line(char *out, int kind /* VX_POP or VX_CLICK */, int loudness);
