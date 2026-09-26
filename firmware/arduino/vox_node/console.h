// Line-based USB serial console (115200, any line ending). `help` lists the commands.
#pragma once
#include <Arduino.h>

void console_poll();
void console_help();
void print_status();
