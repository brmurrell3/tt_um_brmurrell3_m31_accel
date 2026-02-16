![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/formal/badge.svg)

# M31-ACCEL: Mersenne-31 Arithmetic Accelerator

Hardware accelerator for modular arithmetic over the Mersenne-31 prime field (p = 2^31 - 1), taped out on Tiny Tapeout using the IHP sg13g2 130nm process.

## Motivation

ZK-STARKs depend on billions of arithmetic operations over finite fields, and the Mersenne-31 prime (p = 2^31 - 1) has emerged as the field of choice: Plonky3, the proving stack behind SP1 and Valida, uses M31 as its native field. In software, the inner loop of STARK proof generation -- computing large dot products via multiply-accumulate -- dominates runtime and becomes the primary bottleneck. M31-ACCEL offloads this hot path into dedicated hardware. The Mersenne structure enables efficient reduction through bit-folding rather than general-purpose division, making it particularly well-suited to compact digital logic. This accelerator provides single-cycle ADD/SUB and a 32-cycle pipelined MUL/MAC, with a dedicated MAC instruction that computes dot products without round-tripping intermediate results through software.

## Architecture

```
                          8-bit Serial I/O
                     ui_in[7:0]      uo_out[7:0]
                         |               ^
                         v               |
                  +------+------+   +----+----+
                  | Byte Shift  |   |  Byte   |
                  | Register    |   |  Read   |
                  | (LSB-first) |   |  Mux    |
                  +------+------+   +----+----+
                         |               ^
            +------------+------------+  |
            v            v            v  |
       +----+----+  +----+----+  +----+----+
       | reg_a   |  | reg_b   |  | reg_c   |
       | (accum) |  | (oper)  |  | (MAC)   |
       | 32-bit  |  | 32-bit  |  | 32-bit  |
       +----+----+  +----+----+  +----+----+
            |            |            |
            +------+-----+-----+------+
                   |           |
            +------v------+   |
            | ADD/SUB     |   |
            | combinat.   |   |
            | bit-fold +  |   |
            | spec. sub   |   |
            +------+------+   |
                   |     +----v-----+
                   |     | MUL/MAC  |
                   |     | 31-cyc   |
                   |     | shift &  |
                   |     | add      |
                   |     +----+-----+
                   |          |
                   |   +------v------+
                   |   | Double      |
                   |   | bit-fold    |
                   |   | reduction   |
                   |   | 62b -> 31b  |
                   |   | + spec. sub |
                   |   +------+------+
                   |          |
                   |   +------v------+
                   |   | MAC accum   |
                   |   | mul + reg_a |
                   |   | + bit-fold  |
                   |   | + spec. sub |
                   |   +------+------+
                   |          |
                   +----+-----+
                        |
                        v
                   result -> reg_a
                        |
                   BUSY -> uio_out[0]
```

**Key datapath details:**

- **Serial load/read**: 8-bit interface shifts 4 bytes (LSB-first) to fill or read any 32-bit register
- **ADD/SUB**: Combinational bit-folding exploits 2^31 = 1 (mod p); speculative subtraction computes both (fold) and (fold - p) in parallel, selecting via borrow bit
- **MUL/MAC**: MSB-first shift-and-add multiplier runs 31 cycles in the inner loop, followed by 1 pipelined reduction cycle. The operand is captured into a register at multiply start to remove the mux from the critical path
- **Double bit-folding**: 62-bit product is reduced to 31 bits in two fold stages with a final speculative subtraction
- **MAC accumulation**: After reduction, the multiply result is added to reg_a using the same bit-fold + speculative subtraction as ADD

## Features

| Operation | Opcode | Description | Latency |
|-----------|--------|-------------|---------|
| NOP | 0x0 | No operation | 1 cycle |
| ADD | 0x1 | A = (A + B) mod p | 1 cycle |
| SUB | 0x2 | A = (A - B) mod p | 1 cycle |
| MUL | 0x3 | A = (A * B) mod p | 32 cycles |
| CLR | 0x4 | Clear all registers | 1 cycle |
| MAC | 0x5 | A = (A + B * C) mod p | 32 cycles |

Three 32-bit registers: **A** (accumulator, receives all results), **B** (operand for ADD/SUB/MUL, multiplier for MAC), **C** (multiplicand for MAC). All operations reject new commands while BUSY is asserted.

## Quick Start

```
# Reset: hold rst_n low for 5+ clocks, then release

# Load 5 into reg_a (CMD_EN=0, RW=0, REG_SEL=00)
uio_in = 0b0000
ui_in = 0x05; clock    # byte 0 (LSB)
ui_in = 0x00; clock    # byte 1
ui_in = 0x00; clock    # byte 2
ui_in = 0x00; clock    # byte 3 (MSB)

# Load 3 into reg_b (REG_SEL=01)
uio_in = 0b0010
ui_in = 0x03; clock
ui_in = 0x00; clock
ui_in = 0x00; clock
ui_in = 0x00; clock

# Execute ADD (CMD_EN=1, opcode=0x1)
uio_in = 0b0001
ui_in  = 0x01
clock

# Read result from reg_a (CMD_EN=0, RW=1, REG_SEL=00)
uio_in = 0b0100
clock; byte0 = uo_out   # -> 0x08
clock; byte1 = uo_out   # -> 0x00
clock; byte2 = uo_out   # -> 0x00
clock; byte3 = uo_out   # -> 0x00
# Result: 8
```

For MUL and MAC operations, poll the BUSY signal (uio_out[0]) and wait for it to go low before reading the result. Issue a NOP (CMD_EN=1, opcode=0x0) before starting a read sequence to reset the byte counter.

See [docs/info.md](docs/info.md) for the complete interface specification.

## Verification

The design is verified through two complementary methods:

**Simulation (cocotb):** 34 test functions exercising 1,000+ individual assertions across register load/read, all arithmetic operations, edge cases (overflow, underflow, P-1 boundaries, power-of-two folding), BUSY timing and protection, chained operations, mathematical identity checks (commutativity, distributivity), MAC dot products up to 8 terms, and random fuzzing with seeded test vectors.

**Formal (SymbiYosys / Z3):** Bounded model checking to depth 42 proves:
- Functional correctness of ADD and SUB against a reference specification
- Field membership invariant: all four combinational outputs (add_result, sub_result, mul_result, mac_result) remain in [0, p-1]
- reg_a stays in [0, p-1] after every operation write
- Reset clears all registers, counters, and pipeline state
- BUSY signal accurately reflects multiplier and reduction state
- Operands (reg_b, reg_c) are stable throughout multi-cycle operations
- Multiply counter decrements exactly once per cycle and never exceeds 31
- Reduction stage lasts exactly one cycle

## Specifications

| Parameter | Value |
|-----------|-------|
| Target Clock | 66 MHz |
| Technology | IHP sg13g2 130nm |
| Tile Size | 1x2 |
| Utilization | 58% |
| Gate Count | ~1,535 |
| Flip-flops | 228 |
| Latency (ADD/SUB) | 1 cycle |
| Latency (MUL/MAC) | 32 cycles |

## Resources

- [Project Datasheet](docs/info.md)
- [Test Suite](test/test.py)
- [Tiny Tapeout](https://tinytapeout.com)
