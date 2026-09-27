"""EVAL-ONLY whistle patch ("wstrong"), applied in memory: vox_extract/ is not edited and the C port is unchanged.

Proposed (not adopted) fix for whistles on the phone / desk mic. For a whistle-pitched sound (median f0 of its strong
voiced frames >= whistle_min_hz):
  (a) strong-part clarity: if its strong part (frames within contour_db of its level) is >= 90 % voiced, clarity_med
      and voiced_frac are taken over that strong part, so breath / reverb frames stop reading as "noisy" / "talking";
  (b) whistle-band contour: the pitch contour uses only frames >= 0.8 x whistle_min_hz with clarity >= tone_clear, so
      background music / speech under the whistle does not bend its shape.
Offline (2026-09-26): whistle trains in a quiet room 0.62 -> 0.97 right; single whistles over media at 10 dB right
0.27 -> 0.40, wrong action 0.22 -> 0.12; media-alone false alarms unchanged; QBSH contours unchanged; screaming FA/min
3.56 -> 3.71.

    from eval_real import wstrong; wstrong.enable()   # ... run the Extractor ...;  wstrong.disable()
"""
from __future__ import annotations

import inspect

from vox_extract import classify as K
from vox_extract import extractor as E

_src = inspect.getsource(K.classify)
_a1 = "    level = float(np.percentile(e, 90))\n"
_a2 = "    vi, st = clean_pitch(f0, voiced & strong, cfg)\n"
if _src.count(_a1) != 1 or _src.count(_a2) != 1:
    raise ImportError("wstrong: classify.py changed; the patch anchors are gone")
_add1 = "".join("    " + line + "\n" for line in [
    "_strong = e >= level - cfg.contour_db",
    "_sv = voiced & _strong",
    "if WH_STRONG[0] and np.count_nonzero(_strong) >= 3 and np.count_nonzero(_sv) >= 3:",
    "    _vs = np.count_nonzero(_sv) / np.count_nonzero(_strong)",
    "    if float(np.median(f0[_sv])) >= cfg.whistle_min_hz and _vs >= 0.9:",
    "        clar_med = float(np.median(clar[_strong]))",
    "        voiced_frac = float(_vs)",
    "        n_voiced = int(round(voiced_frac * n))",
])
_add2 = "".join("    " + line + "\n" for line in [
    "_pm = voiced & strong",
    "if WH_BAND[0] and np.count_nonzero(_pm) >= 3 and float(np.median(f0[_pm])) >= cfg.whistle_min_hz:",
    "    _pb = _pm & (f0 >= 0.8 * cfg.whistle_min_hz) & (clar >= cfg.tone_clear)",
    "    if np.count_nonzero(_pb) >= 3:",
    "        _pm = _pb",
    "vi, st = clean_pitch(f0, _pm, cfg)",
])
_ns = dict(K.__dict__)
_ns["WH_STRONG"], _ns["WH_BAND"] = [False], [False]
exec(compile(_src.replace(_a1, _a1 + _add1).replace(_a2, _add2), "classify<wstrong>", "exec"), _ns)
patched = _ns["classify"]
WH_STRONG, WH_BAND = _ns["WH_STRONG"], _ns["WH_BAND"]
original = K.classify


def enable(strong: bool = True, band: bool = True) -> None:
    """Route Extractor through the patched classify (the Extractor imports classify by name)."""
    WH_STRONG[0], WH_BAND[0] = strong, band
    E.classify = patched


def disable() -> None:
    WH_STRONG[0] = WH_BAND[0] = False
    E.classify = original
