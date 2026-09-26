"""Runtime patches that make Qwen3.5 (transformers 5.17 + flash-linear-attention 0.5.2) run on ROCm / gfx1151 (Radeon 8060S).

Kernels only: nothing here changes a prompt, a readout or a temperature.

1. transformers' fallback depthwise causal conv (`causal_conv1d_fn`, used when the `causal_conv1d` CUDA package is absent)
   calls F.conv1d(groups=C), which MIOpen rejects on gfx1151 (RuntimeError: miopenStatusUnknownError). It is rebound to
   flash-linear-attention's Triton `causal_conv1d` (same math: depthwise causal conv + optional SiLU).
2. Triton's autotuner (`triton.testing.do_bench`) sizes its loops as rep / (5-run estimate). HIP events report ~0 ms for
   the smallest fla kernels, so it either divides by zero or loops ~1e8 times (hangs). It is replaced by a fixed
   10-repetition timing; autotuning only picks among configs, so results are unchanged.

Triton also needs a C compiler at runtime to build its launcher: run inside `nix shell ... nixpkgs#gcc`.
"""

from __future__ import annotations

_applied = False


def apply() -> None:
    global _applied
    if _applied:
        return
    _patch_do_bench()
    _patch_conv()
    _applied = True


def _patch_do_bench() -> None:
    import triton.testing as tt

    def do_bench(fn, warmup=25, rep=100, grad_to_none=None, quantiles=None, return_mode="mean"):
        import torch

        fn()
        torch.cuda.synchronize()
        times = []
        for _ in range(10):
            s, e = torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True)
            s.record()
            fn()
            e.record()
            torch.cuda.synchronize()
            times.append(max(s.elapsed_time(e), 1e-3))
        times.sort()
        if quantiles is not None:
            out = [times[min(len(times) - 1, int(q * len(times)))] for q in quantiles]
            return out[0] if len(out) == 1 else out
        return {"min": times[0], "max": times[-1], "median": times[len(times) // 2],
                "mean": sum(times) / len(times), "all": times}[return_mode]

    tt.do_bench = do_bench


def _patch_conv() -> None:
    from fla.modules.conv.causal_conv1d import causal_conv1d
    from transformers.models.qwen3_5 import modeling_qwen3_5 as mq

    def causal_conv1d_fn(hidden_states, weight, bias=None, activation=None, **kwargs):
        # transformers layout: hidden_states [B, C, T], weight [C, K]; fla layout: x [B, T, C], weight [C, K]
        y, _ = causal_conv1d(hidden_states.transpose(1, 2), weight, bias, activation=activation)
        return y.transpose(1, 2).to(hidden_states.dtype)

    mq.causal_conv1d_fn = causal_conv1d_fn
