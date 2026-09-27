// The sound vocabulary, a copy of extractor/vox_extract/vocab.py (itself pinned to finetune/vox/schema.py).
// tools/check_extract.sh checks that vx_vocab_json() hashes (sha256, first 16 hex) to Python's vocab.digest(),
// so these tables cannot drift from the Python ones unnoticed.
#pragma once
#include <stddef.h>

#define VX_VOCAB_DIGEST "139d86bd72e13ae5"   // vocab.digest() of the tables below

enum VxContour { VX_RISE, VX_FALL, VX_ARCH, VX_DIP, VX_FLAT, VX_N_CONTOURS };
extern const char *const VX_CONTOUR_KEYS[VX_N_CONTOURS];   // "rise", ...
extern const char *const VX_CONTOURS[VX_N_CONTOURS];       // "rises from low to high", ...
enum VxDiscrete { VX_POP, VX_CLICK, VX_HISS, VX_N_DISCRETE };
extern const char *const VX_DISCRETE_KEYS[VX_N_DISCRETE];  // "pop", "click", "hiss"
extern const char *const VX_DISCRETE[VX_N_DISCRETE];       // "a short lip pop", ...
extern const char *const VX_EXCURSION[3];
extern const char *const VX_DURATION[4];
extern const char *const VX_CLARITY[3];
extern const char *const VX_LOUDNESS[3];
enum VxLike { VX_LIKE_HUM, VX_LIKE_WHISTLE, VX_LIKE_TALKING, VX_LIKE_LAUGHING, VX_LIKE_COUGHING, VX_LIKE_MUSIC,
              VX_LIKE_NOISE, VX_LIKE_MOUTH, VX_N_LIKE };
extern const char *const VX_SOUNDS_LIKE[VX_N_LIKE];

// json.dumps({CLARITY, CONTOURS, DISCRETE, DURATION, EXCURSION, LOUDNESS, SOUNDS_LIKE}, sort_keys=True): the
// text vocab.digest() hashes. Returns the length (snprintf semantics).
size_t vx_vocab_json(char *out, size_t cap);
