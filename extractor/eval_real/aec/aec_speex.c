/* Offline SpeexDSP echo canceller harness for eval_real/aec_desktop.py (nix: speexdsp 1.2.1).
 *
 *   aec_speex <ref.f32> <mic.f32> <out.f32> <rate> <frame> <tail_ms> <supp_db> <supp_active_db>
 *     ref/mic/out: raw mono float32 in [-1, 1]; converted to int16 for speex
 *     frame: samples per frame (e.g. 480 at 48 kHz = 10 ms)
 *     tail_ms: echo tail (filter length)
 *     supp_db / supp_active_db: residual echo suppression in the preprocessor (negative dB; 0 = no preprocessor)
 */
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <speex/speex_echo.h>
#include <speex/speex_preprocess.h>

static float* read_f32(const char* p, long* n) {
  FILE* f = fopen(p, "rb");
  if (!f) { perror(p); exit(2); }
  fseek(f, 0, SEEK_END);
  *n = ftell(f) / 4;
  fseek(f, 0, SEEK_SET);
  float* v = malloc(*n * 4);
  if (fread(v, 4, *n, f) != (size_t)*n) { perror("read"); exit(2); }
  fclose(f);
  return v;
}

static spx_int16_t s16(float x) {
  float y = x * 32767.f;
  if (y > 32767.f) y = 32767.f;
  if (y < -32768.f) y = -32768.f;
  return (spx_int16_t)lrintf(y);
}

int main(int argc, char** argv) {
  if (argc != 9) { fprintf(stderr, "usage: %s ref mic out rate frame tail_ms supp_db supp_active_db\n", argv[0]); return 1; }
  long nr, nm;
  float* ref = read_f32(argv[1], &nr);
  float* mic = read_f32(argv[2], &nm);
  int rate = atoi(argv[4]), frame = atoi(argv[5]), tail = atoi(argv[6]) * rate / 1000;
  int supp = atoi(argv[7]), supp_act = atoi(argv[8]);
  long n = nr < nm ? nr : nm;
  SpeexEchoState* st = speex_echo_state_init(frame, tail);
  speex_echo_ctl(st, SPEEX_ECHO_SET_SAMPLING_RATE, &rate);
  SpeexPreprocessState* pp = NULL;
  if (supp < 0) {
    pp = speex_preprocess_state_init(frame, rate);
    int off = 0;
    speex_preprocess_ctl(pp, SPEEX_PREPROCESS_SET_DENOISE, &off);
    speex_preprocess_ctl(pp, SPEEX_PREPROCESS_SET_AGC, &off);
    speex_preprocess_ctl(pp, SPEEX_PREPROCESS_SET_DEREVERB, &off);
    speex_preprocess_ctl(pp, SPEEX_PREPROCESS_SET_ECHO_STATE, st);
    speex_preprocess_ctl(pp, SPEEX_PREPROCESS_SET_ECHO_SUPPRESS, &supp);
    speex_preprocess_ctl(pp, SPEEX_PREPROCESS_SET_ECHO_SUPPRESS_ACTIVE, &supp_act);
  }
  spx_int16_t *r = malloc(frame * 2), *m = malloc(frame * 2), *o = malloc(frame * 2);
  float* out = calloc(n, 4);
  for (long i = 0; i + frame <= n; i += frame) {
    for (int k = 0; k < frame; k++) { r[k] = s16(ref[i + k]); m[k] = s16(mic[i + k]); }
    speex_echo_cancellation(st, m, r, o);
    if (pp) speex_preprocess_run(pp, o);
    for (int k = 0; k < frame; k++) out[i + k] = o[k] / 32768.f;
  }
  FILE* f = fopen(argv[3], "wb");
  fwrite(out, 4, n, f);
  fclose(f);
  return 0;
}
