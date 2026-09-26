// Bring-up check for the Pico 2 W: blinks the on-board LED (driven through the CYW43 radio chip)
// and prints a heartbeat over USB serial. If the LED blinks, the board, the core and flashing all work.

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(115200);
}

void loop() {
  static uint32_t n = 0;
  digitalWrite(LED_BUILTIN, HIGH);
  delay(250);
  digitalWrite(LED_BUILTIN, LOW);
  delay(750);
  Serial.printf("vox hello %lu, cpu %lu MHz\n", (unsigned long)n++, (unsigned long)(rp2040.f_cpu() / 1000000));
}
