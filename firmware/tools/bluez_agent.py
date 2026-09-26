"""A BlueZ pairing agent with NoInputNoOutput capability, registered for THIS process only.

BlueZ asks an agent to confirm LE Secure Connections "Just Works" pairing; bleak registers none, so without this the
kernel's confirmation request is rejected ("Authentication Failed", SMP reason 0x01). The agent auto-accepts, like
`bluetoothctl` with `agent NoInputNoOutput`. It is used for the Pair call made on the same D-Bus connection, and it
disappears with the process. No system configuration is changed.
"""

from dbus_fast import Message
from dbus_fast.service import ServiceInterface, method

PATH = "/vox/ble_check/agent"


class NoIoAgent(ServiceInterface):
    def __init__(self) -> None:
        super().__init__("org.bluez.Agent1")
        self.calls: list[str] = []

    @method()
    def Release(self):  # noqa: N802
        self.calls.append("Release")

    @method()
    def RequestAuthorization(self, device: "o"):  # noqa: N802,F821
        self.calls.append(f"RequestAuthorization {device}")

    @method()
    def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802,F821
        self.calls.append(f"RequestConfirmation {device} {passkey}")

    @method()
    def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802,F821
        self.calls.append(f"AuthorizeService {uuid}")

    @method()
    def RequestPinCode(self, device: "o") -> "s":  # noqa: N802,F821
        self.calls.append("RequestPinCode")
        return "0000"

    @method()
    def RequestPasskey(self, device: "o") -> "u":  # noqa: N802,F821
        self.calls.append("RequestPasskey")
        return 0

    @method()
    def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802,F821
        self.calls.append("DisplayPasskey")

    @method()
    def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802,F821
        self.calls.append("DisplayPinCode")

    @method()
    def Cancel(self):  # noqa: N802
        self.calls.append("Cancel")

    async def register(self, bus) -> None:
        bus.export(PATH, self)
        await bus.call(Message(destination="org.bluez", path="/org/bluez", interface="org.bluez.AgentManager1",
                               member="RegisterAgent", signature="os", body=[PATH, "NoInputNoOutput"]))

    async def unregister(self, bus) -> None:
        await bus.call(Message(destination="org.bluez", path="/org/bluez", interface="org.bluez.AgentManager1",
                               member="UnregisterAgent", signature="o", body=[PATH]))
