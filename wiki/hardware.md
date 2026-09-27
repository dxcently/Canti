# Hardware: a $7 board and a $3–9 microphone

[Index](index.md) · [Hardware](hardware.md) · [Signal processing](signal-processing.md) · [Gestures and phrases](gesture-vocabulary.md) · [Decision models](decision-models.md) · [Phone control](phone-control.md) · [Prior art](prior-art.md) · [Latency and risks](latency-and-risks.md) · [Roadmap](roadmap.md) · [Sources](sources.md)

**Summary.** Use a Pico 2 W ($7) with an I2S MEMS microphone read through PIO+DMA. The wired build is about $15–20, and $25–32 with a battery [EST]. Keep a Pi or the workstation as the development harness, not as the device. The ESP32 kit works but gains nothing. The "$5 mic/camera boards" add a camera that a sound controller doesn't need.

## The board

The **Raspberry Pi Pico 2 W costs $7** ([Raspberry Pi news](https://www.raspberrypi.com/news/raspberry-pi-pico-2-w-on-sale-now/)). It has two Cortex-M33 cores at 150 MHz, 520 KB SRAM, 4 MB flash and Bluetooth 5.2 ([Pico 2 product page](https://www.raspberrypi.com/products/raspberry-pi-pico-2/)). The M33 cores have a single-precision FPU and the DSP extension. The Hazard3 RISC-V cores have no floating-point extension, so stay on Arm ([RP2350 datasheet](https://datasheets.raspberrypi.com/rp2350/rp2350-datasheet.pdf)). VOX needs no WiFi, so the CYW43439 radio carries only BLE and the WiFi/BLE time-sharing problem goes away ([RPi forums](https://forums.raspberrypi.com/viewtopic.php?t=355693)).

Raspberry Pi's licence lets Pico 2 W owners use **BTstack** commercially, which upstream BTstack otherwise forbids ([pico-sdk LICENSE.RP](https://github.com/raspberrypi/pico-sdk/blob/master/src/rp2_common/pico_btstack/LICENSE.RP)). There are three software routes:

| Route | Notes |
|---|---|
| pico-sdk + BTstack (recommended) | `hog_mouse_demo` sends a 3-byte `{buttons, dx, dy}` report with bonded "Just Works" pairing ([BTstack hog_mouse_demo.c](https://github.com/bluekitchen/btstack/blob/master/example/hog_mouse_demo.c)); GATT server examples in [pico-examples](https://github.com/raspberrypi/pico-examples/blob/master/README.md) |
| arduino-pico | `MouseBLE`/`KeyboardBLE`; costs about 80 KB flash and 20 KB RAM ([arduino-pico docs](https://arduino-pico.readthedocs.io/en/latest/bluetooth.html)) |
| MicroPython | Community HOG libraries; slower DSP |
| CircuitPython | **Out**: it cannot use the Pico W's onboard BLE ([CircuitPython docs](https://docs.circuitpython.org/en/latest/shared-bindings/_bleio/)) |

**Trap:** building with `copy_to_ram` pulls the **~220 KB CYW43 firmware blob into SRAM** ([RPi forums](https://forums.raspberrypi.com/viewtopic.php?t=384445)).

## The microphone

Use a **digital I2S MEMS mic through PIO and DMA**. The RP2350 ADC reaches only about 9.2 effective bits. On the Pico 2 W its reference is the switching supply rail through an RC filter, so "some PSU noise will not be filtered" ([Pico 2 W datasheet](https://datasheets.raspberrypi.com/picow/pico-2-w-datasheet.pdf)). The MAX9814's automatic gain control flattens the energy envelope that the gates rely on ([Adafruit 1713](https://www.adafruit.com/product/1713)).

| Mic | Interface | SNR | Low corner | Price | Caveat |
|---|---|---|---|---|---|
| INMP441 module | I2S, 24-bit | 61 dBA | 60 Hz | ~$2–4 generic [EST] | "Not recommended for new design" ([Digi-Key](https://www.digikey.com/en/products/detail/tdk-invensense/INMP441ACEZ-R7/2606606)); specs via [components101](https://components101.com/modules/inmp441-mems-omnidirectional-microphone) |
| SPH0645 (Adafruit 3421) | I2S, 18-bit | 65 dBA | 50 Hz | $6.95 ([Adafruit](https://www.adafruit.com/product/3421)) | Runs only at 32–64 kHz ([datasheet](https://cdn-shop.adafruit.com/product-files/3421/i2S+Datasheet.PDF)); alignment bugs ([arduino-pico #1353](https://github.com/earlephilhower/arduino-pico/issues/1353)) |
| ICS-43434 (Adafruit 6049) | I2S, 24-bit | 65 dBA | 50 Hz | $8.95 ([Adafruit](https://www.adafruit.com/product/6049)) | Adafruit calls the chip discontinued |
| PDM MEMS (Adafruit 3492) | PDM | 61 dB | n/a | $4.95 ([Adafruit](https://www.adafruit.com/product/3492)) | Needs software decimation |
| MAX9814 / MAX4466 | Analog | n/a | n/a | $7.95 / $6.95 | AGC or ADC noise; avoid |

Prototype with **two or three generic INMP441 modules** (quality varies) and keep an SPH0645 as the fallback. Wire the INMP441 with L/R to GND, and SCK and WS on consecutive GPIOs as PIO requires ([arduino-pico I2S docs](https://arduino-pico.readthedocs.io/en/latest/i2s.html)). A community PIO+DMA driver exists for RP2350 ([pico-inmp441](https://github.com/meta1203/pico-inmp441)).

## Bill of materials

| Item | Price | Source |
|---|---|---|
| Pico 2 W | $7 | [Raspberry Pi](https://www.raspberrypi.com/news/raspberry-pi-pico-2-w-on-sale-now/) |
| I2S mic | $3–9 | table above |
| Breadboard, headers, wires | ~$5–9 | [EST] |
| Pushbutton (cursor mode, disarm/stop, pairing gate) | ~$1 | [EST]. One button on GP14 with the internal pull-up. A 3.5 mm assistive-switch jack was planned but dropped ([D048](decisions.md#d048)); one could be wired in parallel with the button later, as a hardware-only add-on |
| **Wired total** | **~$15–20** | [EST] |
| 500 mAh LiPo + charger (optional) | ~$8–12 | [EST]; VSYS accepts 1.8–5.5 V ([Pico 2 W datasheet](https://datasheets.raspberrypi.com/picow/pico-2-w-datasheet.pdf)) |
| **Battery total** | **~$25–32** | [EST] |

## Alternatives the notes raised

- **Raspberry Pi as the device.** Mostly unnecessary now that the phone is the hub and the workstation handles heavy experiments. The Pi's remaining job is the **development harness**: run the exact float pipeline in Python and try **PESTO** (130k parameters, under 10 ms latency) ([arXiv 2508.01488](https://arxiv.org/html/2508.01488)). The Pi Zero 2 W is $15 but was largely sold out in September 2026 ([raspberry.tips](https://raspberry.tips/en/raspberrypi-infos/raspberry-pi-zero-2-w-alternative-sold-out)), and its BLE HID peripheral mode is do-it-yourself work ([PiKVM docs](https://docs.pikvm.org/bluetooth_hid/)). The 1 GB Pi 5 is $45 ([Raspberry Pi news](https://www.raspberrypi.com/news/1gb-raspberry-pi-5-now-available-at-45-and-memory-driven-price-rises/)).
- **ESP32 kit.** A legitimate alternative: the ESP32-S3 has BLE 5, vector instructions and 512 KB SRAM ([Espressif](https://www.espressif.com/en/products/socs/esp32-s3)), and NimBLE HID-mouse libraries exist ([HijelHID_BLEMouse](https://github.com/HijelHub/HijelHID_BLEMouse)). The Pico is still cheaper, has official HOG examples and has a settled BTstack licence.
- **"$5 mic/camera boards."** Probably ESP32-CAM-class boards. The closest current part is the ~$14 XIAO ESP32S3 Sense with a PDM mic and camera ([Seeed](https://www.seeedstudio.com/XIAO-ESP32S3-Sense-p-5639.html)). The camera adds nothing to a sound controller.

## Open questions / to verify on hardware

- Generic INMP441 quality varies. Measure noise floor and DC offset on each module.
- Does SPH0645's 32 kHz minimum rate need decimation to 16 kHz? The cost is small but still to be written.
- Does **BLE 2M PHY** work on CYW43439 + BTstack? It matters only for streaming audio for spoken phrases ([Phone control](phone-control.md)).
- Battery life under continuous capture plus BLE has not been measured.
- Where to mount the mic (collar, headset boom or desk) affects both SNR and false triggers.
- Whether the "$5 board" in the original notes was actually an ESP32-CAM. Ask the user.
