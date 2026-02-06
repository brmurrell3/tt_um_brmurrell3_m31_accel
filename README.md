![](../../workflows/gds/badge.svg) ![](../../workflows/docs/badge.svg) ![](../../workflows/test/badge.svg) ![](../../workflows/formal/badge.svg)

# M31-ACCEL: Mersenne-31 Arithmetic Accelerator

Hardware accelerator for modular arithmetic over the Mersenne-31 prime field (p = 2³¹ - 1), designed for ZK-STARK and Plonky3 applications.

## Features

- **ADD/SUB**: Single-cycle modular addition and subtraction
- **MUL**: 32-cycle modular multiplication using shift-and-add
- **MAC**: 32-cycle multiply-accumulate for inner products
- **Three 32-bit registers**: A (accumulator), B, C (operands)

## Quick Start

```
# Load 5 into A, 3 into B
# Execute ADD (opcode 0x1)
# Result: A = 8
```

See [docs/info.md](docs/info.md) for complete interface documentation.

## Specifications

| Parameter | Value |
|-----------|-------|
| Target Clock | 50 MHz |
| Tile Size | 1x2 |
| Utilization | 58% |
| Technology | IHP sg13g2 130nm |

## Resources

- [Project Datasheet](docs/info.md)
- [Tiny Tapeout](https://tinytapeout.com)
