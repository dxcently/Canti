// Offline WebRTC APM (AEC3) harness for eval_real/aec_desktop.py.
// Built by aec_desktop.py (nix: webrtc-audio-processing 2.1, the library PipeWire's echo-cancel module uses).
//
//   aec_webrtc <ref.f32> <mic.f32> <out.f32> <rate> <mode> <filter_blocks> <delay_ms> <ns> <supp>
//     ref/mic/out: raw mono float32 in [-1, 1], same rate, same length
//     mode:  aec3   = AEC3 through APM (what PipeWire's webrtc backend runs)
//            mobile = AECM (APM mobile_mode, the old phone-grade canceller)
//     filter_blocks: AEC3 refined/coarse filter length in 64-sample blocks at 16 kHz (4 ms each; default 13 = 52 ms)
//                    0 = library default (no custom factory)
//     delay_ms: value passed to set_stream_delay_ms (AEC3 estimates the delay itself; this is a hint)
//     ns:   0/1 WebRTC noise suppression (PipeWire enables it by default)
//     supp: default | strong | gentle   (AEC3 suppressor masking thresholds)
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>
#include <vector>

#include "api/audio/audio_processing.h"
#include "api/audio/echo_canceller3_config.h"
#include "api/audio/echo_control.h"
#include "modules/audio_processing/aec3/echo_canceller3.h"

namespace {

class Factory : public webrtc::EchoControlFactory {
 public:
  explicit Factory(const webrtc::EchoCanceller3Config& c) : cfg_(c) {}
  std::unique_ptr<webrtc::EchoControl> Create(int rate, int nr, int nc) override {
    return std::make_unique<webrtc::EchoCanceller3>(cfg_, std::nullopt, rate, nr, nc);
  }

 private:
  webrtc::EchoCanceller3Config cfg_;
};

std::vector<float> read_f32(const char* p) {
  FILE* f = fopen(p, "rb");
  if (!f) { perror(p); exit(2); }
  fseek(f, 0, SEEK_END);
  long n = ftell(f) / 4;
  fseek(f, 0, SEEK_SET);
  std::vector<float> v(n);
  if (fread(v.data(), 4, n, f) != (size_t)n) { perror("read"); exit(2); }
  fclose(f);
  return v;
}

}  // namespace

int main(int argc, char** argv) {
  if (argc != 10) {
    fprintf(stderr, "usage: %s ref mic out rate mode filter_blocks delay_ms ns supp\n", argv[0]);
    return 1;
  }
  auto ref = read_f32(argv[1]);
  auto mic = read_f32(argv[2]);
  int rate = atoi(argv[4]);
  std::string mode = argv[5];
  int fblocks = atoi(argv[6]);
  int delay = atoi(argv[7]);
  bool ns = atoi(argv[8]) != 0;
  std::string supp = argv[9];

  webrtc::AudioProcessing::Config c;
  c.echo_canceller.enabled = true;
  c.echo_canceller.mobile_mode = (mode == "mobile");
  c.high_pass_filter.enabled = true;
  c.noise_suppression.enabled = ns;
  c.noise_suppression.level = webrtc::AudioProcessing::Config::NoiseSuppression::kHigh;
  c.gain_controller1.enabled = false;
  c.gain_controller2.enabled = false;

  webrtc::AudioProcessingBuilder b;
  b.SetConfig(c);
  if (mode == "aec3" && (fblocks > 0 || supp != "default")) {
    webrtc::EchoCanceller3Config e;
    if (fblocks > 0) {
      e.filter.refined.length_blocks = fblocks;
      e.filter.coarse.length_blocks = fblocks;
      e.filter.refined_initial.length_blocks = fblocks;
      e.filter.coarse_initial.length_blocks = fblocks;
    }
    if (supp == "strong") {   // suppress more: echo must be further below the near end before it is let through
      e.suppressor.normal_tuning.mask_lf = {.1f, .2f, .3f};
      e.suppressor.normal_tuning.mask_hf = {.03f, .05f, .3f};
      e.suppressor.nearend_tuning.mask_lf = {.5f, .6f, .3f};
      e.suppressor.nearend_tuning.mask_hf = {.05f, .15f, .3f};
      e.ep_strength.default_gain = 2.f;
      e.ep_strength.bounded_erl = false;
    } else if (supp == "gentle") {
      e.suppressor.normal_tuning.mask_lf = {.6f, .8f, .3f};
      e.suppressor.normal_tuning.mask_hf = {.2f, .3f, .3f};
    }
    if (!e.Validate(&e)) fprintf(stderr, "note: AEC3 config adjusted by Validate()\n");
    b.SetEchoControlFactory(std::make_unique<Factory>(e));
  }
  auto apm = b.Create();
  if (!apm) { fprintf(stderr, "APM create failed\n"); return 3; }

  const int hop = rate / 100;
  webrtc::StreamConfig sc(rate, 1);
  size_t n = std::min(ref.size(), mic.size());
  std::vector<float> out(n, 0.f);
  std::vector<float> rbuf(hop), mbuf(hop), obuf(hop), rout(hop);
  for (size_t i = 0; i + hop <= n; i += hop) {
    memcpy(rbuf.data(), &ref[i], hop * 4);
    memcpy(mbuf.data(), &mic[i], hop * 4);
    const float* rin[1] = {rbuf.data()};
    float* ro[1] = {rout.data()};
    const float* min_[1] = {mbuf.data()};
    float* mo[1] = {obuf.data()};
    apm->ProcessReverseStream(rin, sc, sc, ro);
    apm->set_stream_delay_ms(delay);
    apm->ProcessStream(min_, sc, sc, mo);
    memcpy(&out[i], obuf.data(), hop * 4);
  }
  auto st = apm->GetStatistics();
  fprintf(stderr, "stats: erl=%.1f erle=%.1f delay_ms=%d\n", st.echo_return_loss.value_or(-1),
          st.echo_return_loss_enhancement.value_or(-1), st.delay_ms.value_or(-1));
  FILE* f = fopen(argv[3], "wb");
  fwrite(out.data(), 4, n, f);
  fclose(f);
  return 0;
}
