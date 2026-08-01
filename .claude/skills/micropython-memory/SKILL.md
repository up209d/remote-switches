---
name: micropython-memory
description: RAM/flash footprint-minimization playbook for MicroPython on low-memory microcontrollers (Raspberry Pi Pico / RP2040 has 264KB RAM, 2MB Flash; ESP32/ESP8266). Use when the device runs out of memory, throws MemoryError, fragments the heap, or when asked to shrink RAM usage. Covers const() constant privatization, __slots__, gc.collect() tuning, storing immutables in flash instead of RAM, and SD-card storage expansion. Triggers on "micropython out of memory", "MemoryError on pico", "reduce ram usage", "heap fragmentation", "gc.collect", "shrink footprint".
---

# MicroPython Memory Footprint Minimization

A detailed guide to reducing RAM and flash usage of MicroPython programs on
resource-constrained microcontrollers, with REPL-runnable test snippets so
you can verify each technique on-device. Grounds its numbers in real hardware
(e.g. Raspberry Pi Pico: 264KB RAM, 2MB Flash).

**Read the full guide before optimizing:** [`reference/memory-guide.md`](reference/memory-guide.md)

Techniques it covers:
- Core concepts: RAM vs Flash, bytecode, firmware, REPL, the SPI bus.
- Expanding storage with an SD card (FAT/FAT32, `SKIPSD` boot control).
- Constant privatization with `const()` so values live in ROM, not RAM.
- `__slots__` to avoid per-instance `__dict__` overhead.
- Garbage-collection tuning (`gc.collect()`, threshold control) and fighting heap fragmentation.

> Note: the reference guide is written in Chinese. The code examples are language-neutral and directly usable; ask if you want any section summarized or translated into English.
