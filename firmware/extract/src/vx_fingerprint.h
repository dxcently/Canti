// fp1: 24 numbers per sound for phone-side personalization, as extractor/vox_extract/fingerprint.py and
// FINGERPRINT.md. Built from classify's rounded raw values plus the segment's fp1 sums; each value rounded to 4
// decimals. pitch16 (the classifier's smoothed contour at 16 points) is in VxRaw.
#pragma once
#include "vx_classify.h"

#define VX_FP_VERSION "fp1"

void vx_fingerprint(const VxSegStats *seg, VxRaw *raw);   // fills raw->fp
