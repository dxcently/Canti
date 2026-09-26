"""Send one control op to the app's debug socket and print the reply (for manual tests, e.g. BLE on a real phone).

    python3 suite/ctl.py ble_status
    python3 suite/ctl.py ble_scan ms=10000
    python3 suite/ctl.py ble_connect address=auto
    python3 suite/ctl.py ble_config 'config={"v":1,"test_sounds":true}'
    python3 suite/ctl.py config ble_device=null

Arguments are key=value; a value that parses as JSON is sent as JSON (numbers, true/false/null, objects), anything
else as a string. The device is $VOX_SERIAL (default: the suite's emulator), e.g. VOX_SERIAL=<serial from adb devices>.
Needs `adb forward tcp:7788 localabstract:vox-debug` (voxlib does it).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from voxlib import Vox  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help"):
        raise SystemExit(__doc__)
    kw = {}
    for a in sys.argv[2:]:
        k, sep, v = a.partition("=")
        if not sep:
            raise SystemExit(f"argument '{a}' is not key=value")
        try:
            kw[k] = json.loads(v)
        except json.JSONDecodeError:
            kw[k] = v
    r = Vox().control(sys.argv[1], **kw)
    print(json.dumps(r, indent=1))
    sys.exit(0 if r.get("ok") else 1)


if __name__ == "__main__":
    main()
