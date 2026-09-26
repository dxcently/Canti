# servers: local /v1/systemone

`systemone.py` is a FastAPI stand-in for TypeSafe's Jev API with the same request/response format. The Android app's `HttpDecider` talks to it unchanged, so moving to real Jev is only a URL + key change.

- **Request:** `{"state", "model", "questions": {id: {"type": "choice", "instructions", "criteria": {option: description|null}}}}`
- **Response:** `{"model", "answers": {id: {"type": "choice", "choice", "probabilities", "confidence"}}, "usage", "latency_ms"}`, where confidence = (N·p_max − 1)/(N − 1), as Jev defines it.

| model | backend | notes |
|---|---|---|
| `decider-4b` | `teachers.scorer.DeciderTeacher` | General open Jev-like, not trained on VOX. Very slow on CPU (40–220 s per request on a loaded box) |
| `jevk5` | `teachers.scorer.JevK5Teacher` | ≤ 16 options (a single-pass readout) |
| `vox-jevlike` | a `students/jevlike` checkpoint from `VOX_JEVLIKE_CKPT` | Ignores `instructions`; it learned the policy from labels |

```bash
VOX_DEVICE=cpu VOX_THREADS=8 VOX_JEVLIKE_CKPT=runs/<ckpt>.pt uvicorn servers.systemone:app --port 8765
```
Only `choice` questions are served. From the emulator or a phone, run `adb reverse tcp:8765 tcp:8765` (`android/suite/run.sh jev start|stop` does this for the suite).
