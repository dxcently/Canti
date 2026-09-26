# Hardware and output for VOX: low-cost boards, microphones and BLE HID mouse output (as of Sept 2026)

Scope: the Pico 2 W platform, presenting the device as a BLE/USB HID mouse, microphone choices and how to read them on RP2350, the upgrade path (Pi Zero 2 W / 4 / 5, and ESP32-S3 for comparison), and a rough BOM. Every claim has an inline source. Anything that comes only from a forum or a third party is marked [forum] or [3rd-party].

---

## 1. Raspberry Pi Pico 2 W: specs, wireless, RAM/flash budget, HTTPS

### Takeaway
The Pico 2 W costs $7. It has a dual Cortex-M33 (single-precision FPU and DSP extension) or dual Hazard3 RISC-V at 150 MHz, 520 KB SRAM, 4 MB flash, and a CYW43439 radio with 802.11n and Bluetooth 5.2 (LE and Classic). The bundled BTstack licence covers commercial use. WiFi and BLE can run in the same firmware, but they share one radio and one antenna, so only one of them can transmit at any moment. HTTPS works through lwIP + mbedTLS and there are official examples. The main costs are a few tens of KB of RAM for the stacks, and a ~220 KB trap if you build with copy_to_ram.

### Cited Findings
**Price and board**
- Pico 2 W launched at $7, $2 more than the Pico 2. It was announced Nov 25, 2024 — [Raspberry Pi news](https://www.raspberrypi.com/news/raspberry-pi-pico-2-w-on-sale-now/); [CNX Software](https://www.cnx-software.com/2024/11/25/7-raspberry-pi-pico-2-w-board-2-4-ghz-wifi-4-bluetooth-5-2-wireless-module/)
- Raspberry Pi says it does not expect price rises for "classic products" such as Zero 2 W and Pico, because they use older LPDDR2 of which it holds inventory. The RP2040/RP2350 Picos have no DRAM at all — [Raspberry Pi news, Apr 1 2026](https://www.raspberrypi.com/news/a-new-3gb-raspberry-pi-4-for-83-75-and-more-memory-driven-price-increases/)
- Product page: "Dual Arm Cortex-M33 or dual Hazard3 RISC-V processors @ 150MHz", "520 KB on-chip SRAM", "4 MB on-board QSPI flash", "2.4GHz 802.11n wireless LAN and Bluetooth 5.2", 3 ADC channels, 12 PIO state machines — [raspberrypi.com Pico 2 product page](https://www.raspberrypi.com/products/raspberry-pi-pico-2/)
- Pico 2 W datasheet: "Support for Bluetooth LE Central and Peripheral roles", "Support for Bluetooth Classic". The radio is an Infineon CYW43439, connected to the RP2350 over SPI, with an Abracon onboard antenna. There are 26 usable GPIO (23 digital-only, 3 ADC-capable) and a "12-bit 500 ksps" ADC — [Pico 2 W datasheet](https://datasheets.raspberrypi.com/picow/pico-2-w-datasheet.pdf)
- The wireless chip uses GPIO23 (power on), GPIO24 (SPI data/IRQ), GPIO25 (SPI CS) and GPIO29 (SPI CLK, shared with ADC3/VSYS sense). The LED is on WL_GPIO0 and the SMPS power-save pin on WL_GPIO1, both driven through the wireless chip. Keep material away from the antenna area at the board edge or it will detune — [Pico 2 W datasheet](https://datasheets.raspberrypi.com/picow/pico-2-w-datasheet.pdf)
- VSYS input range is 1.8–5.5 V through an onboard buck-boost SMPS, so the board runs from 1 LiPo cell or 2–3 AA cells — [Pico 2 W datasheet](https://datasheets.raspberrypi.com/picow/pico-2-w-datasheet.pdf)

**RP2350 silicon (datasheet)**
- "Dual Cortex-M33 or Hazard3 processors at 150 MHz; 520 kB on-chip SRAM, in 10 independent banks; 8 kB OTP; up to 16 MB external QSPI flash or PSRAM (+ a second 16 MB chip-select)". It also has a hardware SHA-256 accelerator, a TRNG, a USB 1.1 controller+PHY (host/device), 12 PIO state machines and HSTX. The RP2354 variants include 2 MB flash in-package — [RP2350 datasheet §1](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)
- Each Cortex-M33 has "FPU: Single precision FPU", "DSP: DSP extension", security extensions (TrustZone) and a coprocessor interface. RP2350 adds a double-precision coprocessor (DCP) and a GPIO coprocessor — [RP2350 datasheet §3.6–3.7.2](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)
- The Hazard3 RISC-V cores implement `rv32ima_zicsr_zifencei_zba_zbb_zbs_zbkb_zca_zcb_zcmp`, which has no F extension, so there is no hardware floating point on the RISC-V side — [RP2350 datasheet §3.8](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)
- ADC: SAR, "500 kS/s (using an independent 48 MHz clock)", "12-bit with 9.2 ENOB". The electrical table gives ENOB min 9 / typ 9.5 bits and input impedance ≥100 kΩ. The RP2040-E11 DNL spikes are fixed (+~0.5 ENOB vs RP2040) — [RP2350 datasheet §12.4, Table 1438](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)

**WiFi + BLE at the same time**
- A Raspberry Pi engineer (peterharperuk) on the forum: "They can both be used at the same time." Another forum user (not RPi staff) adds that it "cannot receive at all while BT or Wifi are transmitting. It cannot transmit BT and Wifi at the same time." [forum] — [RPi forums t=355693](https://forums.raspberrypi.com/viewtopic.php?t=355693)
- pico-examples ships combined WiFi+BT builds: `gatt_counter_with_wifi`, `gatt_streamer_server_with_wifi` and `spp_streamer_with_wifi` — [pico-examples README](https://github.com/raspberrypi/pico-examples/blob/master/README.md)
- Several users report the BT link dropping at the moment the Pico W joins WiFi [forum] — [RPi forums t=359384](https://forums.raspberrypi.com/viewtopic.php?t=359384); [MicroPython discussion #13615](https://github.com/orgs/micropython/discussions/13615)
- The arduino-pico request to run BT and WiFi together was issue #1837 (Nov 2023), referencing PR #3160. I could not see how it was resolved from the page — [arduino-pico #1837](https://github.com/earlephilhower/arduino-pico/issues/1837)

**RAM and flash taken by the stacks**
- arduino-pico: enabling Bluetooth costs "around 80KB of flash and 20KB of RAM" — [arduino-pico Bluetooth docs](https://arduino-pico.readthedocs.io/en/latest/bluetooth.html)
- The CYW43439 needs four firmware blobs: WLAN, BT, NVRAM and CLM — [cyw43-driver firmware dir](https://github.com/georgerobotics/cyw43-driver/tree/main/firmware)
- Pitfall: on Pico 2 W, building with `pico_set_binary_type(... copy_to_ram)` / `PICO_COPY_TO_RAM=1` puts the combined WiFi+BT firmware blob into SRAM, which costs ~220 kB. Normally it stays in flash. The workaround is to mark the blob `__in_flash(...)` [forum] — [RPi forums t=384445](https://forums.raspberrypi.com/viewtopic.php?t=384445)
- BTstack bonding keys (TLV) are stored in flash. The default `PICO_FLASH_BANK_TOTAL_SIZE` is 2 sectors (8 KB). On RP2350 it sits at the end of flash minus one sector. A custom flash filesystem must avoid this region — [pico-sdk btstack_flash_bank.h](https://github.com/raspberrypi/pico-sdk/blob/master/src/rp2_common/pico_btstack/include/pico/btstack_flash_bank.h)

**HTTPS/TLS**
- pico-examples includes `picow_tls_client` (HTTPS request), `picow_tls_verify` (with certificate verification), `picow_http_client`/`picow_http_client_verify`, and a FreeRTOS `picow_freertos_http_client_sys` — [pico-examples README](https://github.com/raspberrypi/pico-examples/blob/master/README.md)
- The examples link `pico_lwip_mbedtls` + `pico_mbedtls`. The shared mbedTLS config sets `MBEDTLS_SSL_OUT_CONTENT_LEN 2048`, `MBEDTLS_ENTROPY_HARDWARE_ALT` and SNI, and enables RSA and several EC curves. The lwIP config uses `MEM_SIZE 4000`, `TCP_WND 8*MSS` and `TCP_SND_BUF 8*MSS` (MSS 1460) — [pico-examples mbedtls_config_examples_common.h](https://github.com/raspberrypi/pico-examples/blob/master/pico_w/wifi/mbedtls_config_examples_common.h); [lwipopts_examples_common.h](https://github.com/raspberrypi/pico-examples/blob/master/pico_w/wifi/lwipopts_examples_common.h)

### Inferences
- The example config leaves `MBEDTLS_SSL_IN_CONTENT_LEN` at the mbedTLS default (16 KB), so one TLS session probably needs roughly 20–40 KB of heap once handshake buffers are counted. That is fine in 520 KB. This is an estimate and should be measured.
- Keep BLE HID reports flowing while HTTPS traffic is in flight. The radio is time-shared, so a large TLS transfer can delay HID notifications. Keeping the Jev request/response small (text features in, a short command out) helps.
- The FPU and DSP extension on the M33 make floating-point YIN/autocorrelation or FFT at 8–16 kHz practical on one core, leaving the other core for networking and BLE. RISC-V mode loses the FPU, so stay on Arm.
- Use a persistent TLS connection (keep-alive) to Jev. A new handshake per decision adds RSA/ECDHE compute (seconds on an M33 without crypto acceleration is plausible) plus round trips.

### Gaps
- No primary Raspberry Pi document states RAM figures for cyw43+lwIP+BTstack on Pico 2 W. The 20 KB figure comes from arduino-pico.
- No measured TLS handshake time on RP2350 was found.
- No official statement from Raspberry Pi on WiFi/BT coexistence scheduling behaviour, only the forum statements above.

---

## 2. Presenting VOX as a BLE HID mouse (and USB HID fallback)

### Takeaway
There are three workable paths on Pico 2 W: pico-sdk + BTstack `hog_mouse_demo`, the arduino-pico `MouseBLE` library, and MicroPython with a community HOG library. CircuitPython cannot use the Pico W's onboard Bluetooth. iPhone accepts a BLE mouse only when AssistiveTouch is on. BLE HID reports arrive at roughly 66–133 Hz depending on the connection interval the host grants. That is plenty for vocal control, because the cloud round trip will dominate latency. Wired USB HID through TinyUSB is a trivial fallback.

### Cited Findings
**Stacks and examples**
- pico-examples builds BlueKitchen BTstack examples for Pico W boards, including `hog_mouse_demo` (HID Mouse LE), `hog_keyboard_demo` (HID Keyboard LE), `hid_mouse_demo`/`hid_keyboard_demo` (Classic) and `hog_host_demo`. Only a subset build by default; `-DBTSTACK_EXAMPLES_ALL=1` builds all of them. There is also a standalone `bluetooth/ble_pointer` example, an HID mouse driven by an MPU6050 and based on hog_mouse_demo, that pairs as "HID Mouse" — [pico-examples README](https://github.com/raspberrypi/pico-examples/blob/master/README.md); [ble_pointer README](https://github.com/raspberrypi/pico-examples/tree/master/bluetooth/ble_pointer)
- `hog_mouse_demo.c`:
  - Uses a boot-mode-compatible mouse report descriptor: 3 buttons plus 8-bit X/Y, a 3-byte report `{buttons, dx, dy}`.
  - Advertises Appearance 0x03C2 (HID Mouse).
  - Sets `IO_CAPABILITY_NO_INPUT_NO_OUTPUT` with `SM_AUTHREQ_SECURE_CONNECTION | SM_AUTHREQ_BONDING` (Just Works pairing, bonded).
  - Sends through `hids_device_send_input_report` or `hids_device_send_boot_mouse_input_report`.
  - Has a commented-out `gap_request_connection_parameter_update(con_handle, 12, 12, 4, 100)` for a 15 ms interval.
  — [BTstack hog_mouse_demo.c](https://github.com/bluekitchen/btstack/blob/master/example/hog_mouse_demo.c)
- BTstack licence: Raspberry Pi grants purchasers a licence to use BTstack with "Pico W, Pico WH, Pico 2 W, Pico 2 WH, and RM2" and products derived from them. The Pico W announcement calls this "a pre-paid commercial license for BTstack". Upstream BTstack is otherwise non-commercial only — [pico-sdk LICENSE.RP](https://github.com/raspberrypi/pico-sdk/blob/master/src/rp2_common/pico_btstack/LICENSE.RP); [Raspberry Pi news](https://www.raspberrypi.com/news/new-functionality-bluetooth-for-pico-w/); [BTstack LICENSE](https://github.com/bluekitchen/btstack/blob/master/LICENSE)
- arduino-pico (earlephilhower) provides `MouseBLE`, `KeyboardBLE` and `JoystickBLE`, plus Classic `MouseBT`/`KeyboardBT`/`JoystickBT`, "the same API as their USB versions". It is enabled via Tools → IP/Bluetooth Stack. Custom BTstack code must take `BluetoothLock` and must not call `cyw43_arch_init` — [arduino-pico Bluetooth docs](https://arduino-pico.readthedocs.io/en/latest/bluetooth.html)
- MicroPython supports BLE Central and Peripheral on Pico W via `bluetooth`/`aioble` — [Raspberry Pi news](https://www.raspberrypi.com/news/new-functionality-bluetooth-for-pico-w/). HID over GATT is not built in. Community libraries provide it: [Heerkog/MicroPythonBLEHID](https://github.com/Heerkog/MicroPythonBLEHID) (keyboard, mouse, joystick) and [prsh9/pico-w-bluetooth-hid](https://github.com/prsh9/pico-w-bluetooth-hid) (3-button mouse + wheel) [3rd-party]
- CircuitPython: "Pico W boards do not support BLE using the on-board CYW43 co-processor". The feature request (#7693, Mar 2023) is still open under the "Long term" milestone — [CircuitPython _bleio docs](https://docs.circuitpython.org/en/latest/shared-bindings/_bleio/); [circuitpython #7693](https://github.com/adafruit/circuitpython/issues/7693)

**Host OS behaviour**
- iPhone/iPad: pointer devices (Bluetooth or wired mouse or trackpad) work through AssistiveTouch. The path is Settings → Accessibility → Touch → AssistiveTouch → Devices → Bluetooth Devices, then turn AssistiveTouch on to get the grey circular pointer. Dwell options allow clicks without pressing buttons (Movement Tolerance plus a time delay) — [Apple Support 111775](https://support.apple.com/en-us/111775). Apple added mouse support to AssistiveTouch in iOS 13 — [Wikipedia: AssistiveTouch](https://en.wikipedia.org/wiki/AssistiveTouch)
- Connection intervals on Apple hosts: the Accessory Design Guidelines set a minimum interval of 15 ms, versus 7.5 ms in the Bluetooth core spec — [Silicon Labs summary of Apple ADG](https://docs.silabs.com/bluetooth/9.1.1/mobile-apps-suitable-connection-parameters/). Apple QA1931 says "If Bluetooth Low Energy HID is one of the connected services... connection interval down to 11.25 ms may be accepted" (quoted in search results; see also [Apple dev forum thread](https://developer.apple.com/forums/thread/796428)).
- A 7.5 ms interval corresponds to about 133 Hz report rate, the fastest standard BLE interval before Bluetooth 6.2's Shorter Connection Intervals — [Novel Bits](https://novelbits.io/ble-shorter-connection-intervals-hands-on-nrf54l15/). An application note says HID mice typically need 60 Hz updates, so a 15 ms interval is common — [Goodix BLE HID app note](https://goodix-ble-wiki-en.readthedocs.io/latest/AppNote/BLE/BLE%E5%BA%94%E7%94%A8/BLE%20HID%E5%BA%94%E7%94%A8%E7%AC%94%E8%AE%B0.html) [3rd-party]
- The ESP32 NimBLE mouse library HijelHID_BLEMouse claims it works with iOS, Android, macOS, Windows and Linux. This is useful evidence that one standard HOG mouse descriptor is accepted across all five [3rd-party] — [HijelHID_BLEMouse](https://github.com/HijelHub/HijelHID_BLEMouse)
- Pi-based Bluetooth HID (PiKVM): "Bluetooth mouse can work only in relative mode... many Bluetooth host drivers do not correctly implement HID descriptors", and horizontal scroll is unsupported. It was tested only on Pi 4 — [PiKVM docs](https://docs.pikvm.org/bluetooth_hid/)

**USB HID fallback**
- pico-examples builds TinyUSB device examples such as `tinyusb_dev_hid_composite` (keyboard+mouse) — [pico-examples README](https://github.com/raspberrypi/pico-examples/blob/master/README.md). RP2350 has a USB 1.1 device controller and PHY — [RP2350 datasheet](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf). arduino-pico's USB Mouse shares its API with MouseBLE — [arduino-pico Bluetooth docs](https://arduino-pico.readthedocs.io/en/latest/bluetooth.html)
- Apple lists wired mice as supported pointer devices, so a USB-C iPhone or iPad with an adapter also works via AssistiveTouch — [Apple Support 111775](https://support.apple.com/en-us/111775)

### Inferences
- Use relative mouse reports (dx/dy int8 + buttons) exactly as in `hog_mouse_demo`. Absolute or digitizer descriptors are poorly supported over Bluetooth (PiKVM evidence), and iOS expects a mouse, not a tablet.
- Latency budget: BLE adds about one connection interval (7.5–30 ms) per report. The cloud round trip to Jev (hundreds of ms or more) dominates. For smooth motion, Jev should send intent ("move left at speed 3 until stopped") and the Pico should generate the individual HID reports locally at 60–100 Hz. It should not send one cloud call per report. This is a design recommendation and is not sourced.
- iOS users must enable AssistiveTouch once, and ideally configure Dwell or button mapping. VOX's "click" events map to HID button 1. Double-click and long-press can be mapped in AssistiveTouch custom actions.
- Just Works pairing is fine for a mouse but unauthenticated. Bonding keys persist in the 8 KB flash bank noted above.
- Android, Windows 10/11, macOS and Linux (BlueZ) all have native HOGP host support. I found no primary doc for each, but the cross-platform ESP32 library report above is consistent with that.

### Gaps
- I found no published test of the Pico W or Pico 2 W `hog_mouse_demo` specifically with iOS. Only general AssistiveTouch docs and the ESP32 library claim exist.
- I could not fetch Apple's current Accessory Design Guidelines PDF (R21+) directly. The 11.25 ms HID figure comes via secondary quotes of QA1931.
- I found no measured end-to-end BLE HID latency numbers for CYW43439.

---

## 3. Microphones: I2S MEMS vs PDM vs analog electret, and reading them on RP2350

### Takeaway
For hum pitch tracking from 80 to 1000 Hz, any of these will do. The cheapest good option is a digital I2S MEMS module read over PIO+DMA: INMP441 (24-bit, 61 dBA, flat from 60 Hz) or the Adafruit ICS-43434/SPH0645 (65 dBA). They avoid the Pico's noisy SMPS/ADC analog path. The analog MAX9814 is easy to wire, but its AGC distorts the energy features and the RP2350 ADC is only ~9.2 ENOB. PDM needs software decimation. Recommended pick: INMP441 for the absolute lowest cost, or ICS-43434 / SPH0645 (Adafruit, documented) if you want a supported breakout.

### Cited Findings
**Candidates**
- **INMP441 (TDK InvenSense, I2S)**
  - Specs: 61 dBA SNR, −26 dBFS sensitivity, "flat frequency response from 60 Hz to 15 kHz", 24-bit I2S, 1.8–3.3 V, 1.4 mA. L/R low → left channel, high → right channel [3rd-party spec summary] — [components101](https://components101.com/modules/inmp441-mems-omnidirectional-microphone)
  - The L/R pin must be tied to VDD or GND to match software. The −3 dB low corner is 60 Hz — [Digi-Key INMP441 datasheet page](https://www.digikey.com/htmldatasheets/production/1431884/0/0/1/inmp441-datasheet.html) (via search snippet; page now returns 410)
  - Distributor listings mark INMP441 "not recommended for new design", with ICS-43434 as the substitute — [TDK INMP441 resources / Digi-Key listing](https://www.digikey.com/en/products/detail/tdk-invensense/INMP441ACEZ-R7/2606606)
- **ICS-43434 (TDK, I2S), Adafruit #6049**
  - $8.95. SNR 65 dBA (HP mode) / 64 dBA (LP). −26 dBFS. 50 Hz–15 kHz. 24-bit I2S. Sample rate 23–51.6 kHz in HP mode, 6.25–18.75 kHz in low-power mode. 1.6–3.6 V. Listed as working with "RP2040 or RP2350".
  - The page says the ICS-43434 chip is discontinued and names SPH0645LM4H as a "drop-in replacement".
  — [Adafruit 6049](https://www.adafruit.com/product/6049)
- **SPH0645LM4H-B (Knowles, I2S), Adafruit #3421**
  - $6.95, in stock, 50 Hz–15 kHz, 1.6–3.6 V, bottom-ported — [Adafruit 3421](https://www.adafruit.com/product/3421)
  - Datasheet: SNR 65 dB(A), sensitivity −26 dBFS typ.
  - Clock 2.048–4.096 MHz with fixed OSR 64, so the sample rate is **32–64 kHz only**. Sleep below 900 kHz.
  - "Data Format is I2S, 24 bit, 2's compliment, MSB first. The Data Precision is 18 bits, unused bits are zeros." It requires "I2S with MSB delayed 1 BCLK cycle after WS changes".
  - SELECT high → data driven when WS=H. Use a 100 kΩ pull-down on DATA for a single mic. Power-up time ≤50 ms.
  — [Knowles SPH0645LM4H-B datasheet (Adafruit mirror)](https://cdn-shop.adafruit.com/product-files/3421/i2S+Datasheet.PDF)
- **MSM261S4030H0 (MEMSensing, I2S)**: SNR 57 dB(A), −26 dBFS, 1.6–3.6 V, 24-bit in a 32-bit word with 64 SCK per stereo frame — [MSM261S4030H0 datasheet (makerhero mirror)](https://www.makerhero.com/img/files/download/Microfone-Sipeed-MSM261S4030H0-Datasheet.pdf)
- **PDM MEMS (Adafruit #3492)**: $4.95, SNR 61 dB, PDM clock 1–3.25 MHz, 1.8–3.3 V, 0.6 mA. Adafruit warns "these chips are a little tricky" without a hardware PDM peripheral — [Adafruit 3492](https://www.adafruit.com/product/3492)
- **MAX9814 electret + AGC (Adafruit #1713)**: $7.95. Gain 40/50/60 dB. AGC attack/release ratio 1:500, 1:2000 or 1:4000. Output "about 2Vpp max on a 1.25V DC bias", suitable for 3.3 V ADCs. Electret mic rated 20 Hz–20 kHz — [Adafruit 1713](https://www.adafruit.com/product/1713)
- **MAX4466 electret (Adafruit #1063)**: $6.95. Gain 25×–125× set by trimpot. Output biased at VCC/2 and rail-to-rail. Supply 2.4–5 V. Adafruit advises the "quietest" supply — [Adafruit 1063](https://www.adafruit.com/product/1063)

**Reading them on RP2350**
- **I2S input**
  - RP2350 has no hardware I2S, so it is done in PIO. arduino-pico's `I2S(INPUT)` supports 8/16/24/32-bit samples, with the constraint "LRCLK/word clock will be pin + 1" — [arduino-pico I2S docs](https://arduino-pico.readthedocs.io/en/latest/i2s.html)
  - Community pico-sdk libraries: [meta1203/pico-inmp441](https://github.com/meta1203/pico-inmp441) (PIO+DMA, RP2040 and RP2350), [mryndzionek/rp2040_pico_sdk_playground](https://github.com/mryndzionek/rp2040_pico_sdk_playground) (INMP441 + fixed-point FFT) and [malacalypse/rp2040_i2s_example](https://github.com/malacalypse/rp2040_i2s_example) (bidirectional 24-bit) [3rd-party]
- **PDM and analog**: [ArmDeveloperEcosystem/microphone-library-for-pico](https://github.com/ArmDeveloperEcosystem/microphone-library-for-pico) supports the Adafruit PDM breakout (GPIO2 DAT, GPIO3 CLK), using OpenPDM2PCM for decimation, and the analog MAX9814 on GPIO26. It is tested on RP2040 and lists no RP2350 notes. It is "not an official Arm product".
- **SPH0645 quirks**
  - The mic changes data on the same edge some hosts sample on, so every 18-bit sample shifts one bit and the MSB is lost; it also appears to output half a BCLK early [3rd-party/forum] — [Hackaday.io log](https://hackaday.io/project/162059-street-sense/log/160705-new-i2s-microphone); [RPi forum t=306880](https://forums.raspberrypi.com/viewtopic.php?t=306880)
  - arduino-pico issue #1353 reports the SPH0645 being left-aligned 24-bit when the library expects right-aligned, plus slow callbacks. It was never resolved ("waiting for feedback") — [arduino-pico #1353](https://github.com/earlephilhower/arduino-pico/issues/1353)
- **RP2350 ADC for analog mics**
  - 500 kS/s, 9.2 ENOB (9 min / 9.5 typ), input impedance ≥100 kΩ — [RP2350 datasheet §12.4](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)
  - On Pico 2 W, ADC_VREF is the 3.3 V SMPS rail through a 201 Ω / 2.2 µF RC filter, so "some PSU noise will not be filtered", with a ~30 mV offset.
  - Driving WL_GPIO1 high forces the SMPS into PWM mode, which "can greatly reduce the inherent ripple".
  - An external LM4040 3.0 V shunt reference gives "much improved ADC performance".
  — [Pico 2 W datasheet §3.3–3.4](https://datasheets.raspberrypi.com/picow/pico-2-w-datasheet.pdf)

### Inferences
- 9.2 ENOB corresponds to roughly 57 dB ideal SNR (6.02×9.2+1.76). Board noise brings the real figure lower. I2S MEMS parts deliver 61–65 dBA at the capsule with no analog routing, so digital is the better pick for a noise-sensitive energy/pitch front end.
- **Sample rate**
  - Hums at 80–1000 Hz need only 8–16 kHz. INMP441 and ICS-43434 (HP mode ≥23 kHz) run at 16 kHz or higher. Decimate as needed.
  - The SPH0645 cannot go below 32 kHz. Decimating by 2–4 in software is cheap on the M33 (DSP extension).
  - At 32 kHz × 32-bit slots mono, DMA traffic is ~128 KB/s, which is trivial.
- **Low-frequency response**
  - INMP441's 60 Hz −3 dB corner is just below the lowest male hum fundamentals (~80–100 Hz).
  - For very low hums, the pitch tracker may lock onto the 2nd harmonic. YIN/autocorrelation methods handle a weak fundamental better than a plain FFT peak pick.
- **MAX9814 AGC** compresses loudness, which fights VOX's energy features (for example "louder = faster"). If using an analog mic, set a fixed gain or choose the MAX4466. Alternatively, derive energy from a digital mic instead.
- **Wiring an INMP441 to a Pico**
  - VDD→3V3, GND→GND, L/R→GND (left).
  - SCK→GPIO n, WS→GPIO n+1 (consecutive pins for PIO), SD→any GPIO.
  - Keep wires short. Datasheet guidance on RF filter caps (20–200 pF) for SPH0645 suggests the same for WiFi-adjacent builds.
- **Cheap INMP441 modules**
  - They come from generic sellers. Quality varies and the part is not recommended for new designs, so buy 2–3 spares.
  - For a product-grade build, use ICS-43434/SPH0645 or a current TDK part.

### Gaps
- No primary TDK INMP441 datasheet text could be fetched: TDK's URL serves HTML, Mouser's is gated and Digi-Key's returns 410. The SCK range, startup time and HPF corner for INMP441 are unconfirmed here.
- There is a conflict on ICS-43434 status. Adafruit calls the ICS-43434 discontinued, while distributor listings name it as the INMP441 substitute. Current TDK lifecycle status is unverified.
- Frequency response and part number for the Adafruit PDM breakout (#3492) were not on the page. It is commonly an MP34DT01-class part, which is unverified.
- Street prices for bare INMP441/MSM261 modules (AliExpress/Amazon) were not captured from a reliable source.

---

## 4. Upgrade path: Pi Zero 2 W / Pi 4 / Pi 5, and ESP32-S3 for comparison

### Takeaway
A Pi Zero 2 W ($15 MSRP, but hard to find in 2026) gives a full Linux/Python stack (numpy, librosa-style pitch tools, small local ML) and USB gadget HID. Its BLE HID peripheral mode through BlueZ is DIY and less polished than BTstack on Pico. Pi 4/5 prices rose sharply in 2026 due to LPDDR4 costs; the new 1 GB Pi 5 at $45 is the cheapest high-performance option. The ESP32-S3 (BLE 5 only, native USB, vector instructions, 512 KB SRAM + PSRAM) is the closest MCU competitor. The $14 XIAO ESP32S3 Sense already has a PDM mic and camera onboard.

### Cited Findings
**Raspberry Pi Zero 2 W**
- RP3A0 SiP, quad Cortex-A53 @ 1 GHz, 512 MB SDRAM, 802.11b/g/n and "Bluetooth 4.2, Bluetooth Low Energy (BLE)", micro-USB OTG port — [Zero 2 W product page](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/)
- Launched at $15 — [Raspberry Pi news](https://www.raspberrypi.com/news/new-raspberry-pi-zero-2-w-2/)
- 2026 supply: Raspberry Pi blamed AI-driven substrate demand (May 2026), qualified a second substrate vendor, expected improvement in H2 2026, and committed to production until at least Jan 2030. As of mid-Sept 2026 major resellers were sold out, with PiShop.us at $17.25 (limit 1) [3rd-party] — [raspberry.tips](https://raspberry.tips/en/raspberrypi-infos/raspberry-pi-zero-2-w-alternative-sold-out); see also [RPi forum t=398799](https://forums.raspberrypi.com/viewtopic.php?t=398799)
- USB HID gadget: enable with `dtoverlay=dwc2` plus the `dwc2` and `libcomposite` modules, then configure a HID function under `/sys/kernel/config/usb_gadget/`. The config is volatile and must be recreated at each boot [3rd-party] — [iSticktoit composite gadget guide](https://www.isticktoit.net/?p=1383); [Random Nerd Tutorials](https://randomnerdtutorials.com/raspberry-pi-zero-usb-keyboard-hid/)

**Bluetooth HID on Pi (BlueZ)**
- Most projects emulate **Classic** HID. They register an SDP record via `org.bluez.ProfileManager1.RegisterProfile` and send reports over L2CAP, usually as root [3rd-party] — [AnesBenmerzoug/Bluetooth_HID](https://github.com/AnesBenmerzoug/Bluetooth_HID); [scientificRat gist](https://gist.github.com/scientificRat/be2bbac0769bfa04820bc73edc009bdf)
- A BlueZ **HOGP** (BLE) keyboard emulator example exists as a D-Bus GATT server [3rd-party] — [HeadHodge HOGP gist](https://gist.github.com/HeadHodge/2d3dc6dc2dce03cf82f61d8231e88144)
- PiKVM's Bluetooth HID is tested only on Pi 4, supports relative mouse only, and uses the UART — [PiKVM docs](https://docs.pikvm.org/bluetooth_hid/)

**Pi 4 / Pi 5 pricing (2026)**
- Feb 2, 2026: increases on 2 GB+ Pi 4/5/CM4/CM5 of +$10 (2 GB), +$15 (4 GB), +$30 (8 GB) and +$60 (16 GB). 1 GB models are unchanged. Zero, Pi 3 and older are not expected to change — [Raspberry Pi news](https://www.raspberrypi.com/news/more-memory-driven-price-rises/)
- Apr 1, 2026: a further +$25 (4 GB), +$50 (8 GB) and +$100 (16 GB Pi 5). A new 3 GB Pi 4 costs $83.75. The 1 GB and 2 GB Pi 4/5 models sit "between $35 and $65" — [Raspberry Pi news](https://www.raspberrypi.com/news/a-new-3gb-raspberry-pi-4-for-83-75-and-more-memory-driven-price-increases/)
- The 1 GB Pi 5 launched at $45 — [Raspberry Pi news](https://www.raspberrypi.com/news/1gb-raspberry-pi-5-now-available-at-45-and-memory-driven-price-rises/)
- The 16 GB Pi 5 went $120 → $145 (Dec 2025) → $205 (Feb 2026) → $305 (Apr 2026) — [Tom's Hardware](https://www.tomshardware.com/raspberry-pi/raspberry-pi-5-price-increases-drastically-as-ai-shortage-bites-16gb-version-now-usd205-second-price-increase-in-three-months-over-70-percent-more-expensive-than-original-msrp); [Electronics Weekly](https://www.electronicsweekly.com/news/business/raspberrypi-price-hikes-2026-04/)

**ESP32-S3 (comparison)**
- "dual-core XTensa LX7 MCU, capable of running at 240 MHz", "512 KB of internal SRAM", octal SPI flash/PSRAM, "2.4 GHz, 802.11 b/g/n Wi-Fi and Bluetooth 5 (LE)" (no Classic), and "vector instructions... for neural network computing and signal processing". It has I2S and ADC — [Espressif ESP32-S3](https://www.espressif.com/en/products/socs/esp32-s3)
- The Seeed XIAO ESP32S3 Sense costs about $14. It has 8 MB PSRAM and 8 MB flash, an OV2640 camera, a PDM microphone and microSD, in a 21 × 17.5 mm board — [Seeed product page](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html); [Amazon listing](https://www.amazon.com/Seeed-Studio-XIAO-ESP32-Sense/dp/B0C69FFVHH)
- BLE HID mouse on ESP32 comes from NimBLE-based Arduino libraries such as HijelHID_BLEMouse and ESP32-NimBLE-Mouse. The ESP32-S3 is needed to get BLE and native USB on one chip [3rd-party] — [HijelHID_BLEMouse](https://github.com/HijelHub/HijelHID_BLEMouse); [esp32beans/BLE_HID_Client](https://github.com/esp32beans/BLE_HID_Client)

### Inferences
- **What a Pi adds**
  - Python and numpy for fast iteration on pitch/feature code (librosa, crepe-tiny, or small keyword/sound classifiers via TFLite or ONNX Runtime).
  - Enough RAM to buffer seconds of audio.
  - A standard TLS stack.
  - Optionally, running the "decision" model locally instead of calling Jev, which would remove the cloud latency.
- **What a Pi costs**
  - Boot time: tens of seconds.
  - Power: a Pi 5 needs a much larger supply than a Pico.
  - An SD card is required.
  - BLE HID peripheral on Linux is DIY. Most tutorials use Classic HID, which iPhone may treat differently from a BLE mouse; this is unverified.
- **USB input**: a USB mic plugged into a Zero 2 W needs an OTG adapter, and that port is also the only USB gadget port. So a Zero 2 W cannot be a USB HID gadget and host a USB mic at the same time. Use an I2S MEMS mic on the Zero instead (INMP441 or SPH0645 via device-tree overlay), or BLE HID output.
- **ESP32-S3 vs Pico 2 W**
  - The ESP32-S3 has a more mature combined WiFi+BLE coexistence story (ESP-IDF), PSRAM options, and the all-in-one XIAO Sense with a mic.
  - The Pico 2 W is cheaper ($7) and has official HOG examples plus a licensed BTstack.
  - Either works. The Pico matches the stated primary board.
- The "$5 mic/camera boards" in the original plan are probably ESP32-CAM-class boards. The XIAO ESP32S3 Sense is the current small mic+camera option at about $14.

### Gaps
- No official Raspberry Pi doc on USB device/gadget mode on the Pi 4 and Pi 5 USB-C port was fetched. It is widely reported to work via dwc2 but is not cited here.
- No primary source on the BLE (vs Classic) HID peripheral reliability of BlueZ with iOS.
- The complete current US price list for each Pi 4/5 SKU after the Apr 2026 changes was not published in one table in the sources fetched. Per-SKU prices must be computed from the increments or checked with resellers.
- The ESP32-S3 official page did not state USB OTG or PDM support explicitly. Other Espressif docs, not fetched, cover them.

---

## 5. Suggested bill of materials (approximate, Sept 2026, USD)

### Takeaway
A Pico 2 W build costs about $15–30 depending on the mic and whether it is battery powered. A Zero 2 W build costs about $35–50 if you can find the board. A Pi 5 (1 GB) build starts around $80–100 with a supply and SD card.

### Cited Findings (component prices with sources)
- Pico 2 W: $7 — [Raspberry Pi news](https://www.raspberrypi.com/news/raspberry-pi-pico-2-w-on-sale-now/)
- Adafruit SPH0645 I2S breakout: $6.95 — [Adafruit 3421](https://www.adafruit.com/product/3421)
- Adafruit ICS-43434 I2S breakout: $8.95 — [Adafruit 6049](https://www.adafruit.com/product/6049)
- Adafruit PDM MEMS breakout: $4.95 — [Adafruit 3492](https://www.adafruit.com/product/3492)
- Adafruit MAX9814 (AGC): $7.95 — [Adafruit 1713](https://www.adafruit.com/product/1713)
- Adafruit MAX4466: $6.95 — [Adafruit 1063](https://www.adafruit.com/product/1063)
- Pi Zero 2 W: $15 MSRP — [Raspberry Pi news](https://www.raspberrypi.com/news/new-raspberry-pi-zero-2-w-2/). Street price $17.25+ when in stock [3rd-party] — [raspberry.tips](https://raspberry.tips/en/raspberrypi-infos/raspberry-pi-zero-2-w-alternative-sold-out)
- Pi 5 1 GB: $45 — [Raspberry Pi news](https://www.raspberrypi.com/news/1gb-raspberry-pi-5-now-available-at-45-and-memory-driven-price-rises/)
- XIAO ESP32S3 Sense: about $14 — [Seeed](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html)

### Inferences (draft BOMs; unsourced line items marked ~est)
**A. Pico 2 W build (primary)**
| Item | Price |
|---|---|
| Raspberry Pi Pico 2 W | $7 |
| Mic: INMP441 module (~est $2–4, generic) or Adafruit SPH0645 ($6.95) or ICS-43434 ($8.95) | $3–9 |
| Micro-USB cable (power + USB HID fallback) | ~est $2–4 |
| Headers/breadboard/jumpers | ~est $3–5 |
| Optional: LiPo 500 mAh + charger board (VSYS accepts 1.8–5.5 V) | ~est $8–12 |
| Optional: pushbutton for pairing/"panic stop" | ~est $0.5 |
| **Total** | **~$15–20 wired; ~$25–32 battery** |

**B. Pi Zero 2 W build (upgrade)**
| Item | Price |
|---|---|
| Raspberry Pi Zero 2 W | $15 MSRP ($17+ street, scarce) |
| microSD 16–32 GB | ~est $6–10 |
| I2S mic (INMP441 / SPH0645) — avoids occupying the only OTG port | $3–9 |
| 5 V 2.5 A micro-USB supply | ~est $8–10 |
| Header/soldering | ~est $2 |
| **Total** | **~$35–50** |

**C. Pi 5 (1 GB) variant**: $45 board + ~est $12 official 27 W supply + ~est $8 SD + $3–9 mic (or a ~est $5–10 USB mic) ≈ **$70–85**. It supports local ML more comfortably, but it is overkill if Jev does the decisions.

Notes:
- Buy 2 of each mic, since cheap modules vary in quality.
- If the build will feed an analog mic into the ADC, add an LM4040 3.0 V reference (~est $1).

### Gaps
- Prices for generic INMP441 modules, cables, LiPo and chargers, SD cards and supplies are estimates, not sourced.
- The Pico 2 WH (pre-soldered headers) price was not confirmed.
- The official Pi 5 27 W PSU price was not re-checked for 2026.
