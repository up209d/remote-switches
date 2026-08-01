---
name: micropython-performance
description: Speed-optimization playbook for MicroPython on microcontrollers (Raspberry Pi Pico / RP2040, ESP32). Use when MicroPython code is slow, when profiling execution time, or when asked to speed up a loop, ISR, or hot path. Covers timing/profiling with time.ticks_us, reducing GC pressure, const(), the @micropython.native and @micropython.viper emitters, and integer-vs-float / register / DMA tradeoffs. Triggers on "make micropython faster", "optimize pico performance", "slow loop on device", "native viper emitter", "reduce gc".
---

# MicroPython Performance Optimization

A detailed, hardware-verified guide to speeding up MicroPython code, ordered
from cheapest to most invasive: profile → memory/object optimization →
bytecode & native/viper emitters → arithmetic/hardware (integer math,
direct register access, DMA). It targets microcontrollers specifically,
including the Raspberry Pi Pico.

**Read the full guide before optimizing:** [`reference/optimization-guide.md`](reference/optimization-guide.md)

The workflow it prescribes:
1. Identify the slowest code with real timing (`time.ticks_us`, a `@timed_function` decorator) — measure, don't guess.
2. Cut heap allocation and dynamic object creation to lower GC frequency.
3. Improve execution efficiency: `const()`, precompiled bytecode, and the `@micropython.native` / `@micropython.viper` code emitters.
4. Push to hardware: integers over floats, direct register manipulation, DMA.

> Note: the reference guide is written in Chinese. The code examples are language-neutral and directly usable; ask if you want any section summarized or translated into English.
