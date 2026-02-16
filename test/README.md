# M31-ACCEL Test Suite

Cocotb testbench for the Mersenne-31 arithmetic accelerator. Covers all operations (ADD, SUB, MUL, MAC, CLR, NOP), edge cases, timing, and mathematical properties.

## Test Summary

| Category | Tests | Vectors |
|----------|-------|---------|
| Register load/read | 2 | 4 |
| Arithmetic (ADD, SUB, MUL) | 4 | 17 |
| Boundary cases | 3 | 43 |
| Timing and control | 4 | - |
| Random + edge grid | 1 | 663 |
| Mathematical identities | 1 | 4 |
| MAC operation | 12 | 400+ |
| Out-of-range inputs | 1 | 5 |
| **Total** | **34** | **1000+** |

## Running Tests

```sh
make -B
```

Gate-level simulation (requires hardened netlist):

```sh
make -B GATES=yes
```

## Viewing Waveforms

```sh
gtkwave tb.fst tb.gtkw    # GTKWave
surfer tb.fst              # Surfer
```

## Test Architecture

Tests use helper functions for the byte-serial interface protocol:

- `init_dut(dut)` - Start clock and reset
- `load_register(dut, value, reg_sel)` - 4-byte serial write
- `read_register(dut, reg_sel)` - 4-byte serial read
- `execute_opcode(dut, opcode)` - Single-cycle operation
- `execute_mul(dut)` / `execute_mac(dut)` - Multi-cycle with BUSY polling
