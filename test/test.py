# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
import random

P = 2**31 - 1  # Mersenne-31 prime


async def reset_dut(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0b100
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


async def load_register(dut, value, reg_sel):
    dut.uio_in.value = (reg_sel << 1) | 0b000
    dut.ui_in.value = 0
    for i in range(4):
        byte_val = (value >> (i * 8)) & 0xFF
        dut.ui_in.value = byte_val
        await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100
    dut.ui_in.value = 0


async def read_register(dut, reg_sel):
    dut.uio_in.value = (reg_sel << 1) | 0b100
    result = 0
    for i in range(4):
        await ClockCycles(dut.clk, 1)
        byte_val = int(dut.uo_out.value)
        result |= (byte_val << (i * 8))
    return result


async def execute_opcode(dut, opcode):
    dut.uio_in.value = 0b001
    dut.ui_in.value = opcode
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100


async def execute_mul(dut):
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x3
    await ClockCycles(dut.clk, 2)
    dut.ui_in.value = 0x0
    cycle_count = 0
    while int(dut.uio_out.value) & 0x01:
        await ClockCycles(dut.clk, 1)
        cycle_count += 1
        assert cycle_count < 40, "BUSY stuck high"
    dut.uio_in.value = 0b100
    return cycle_count


@cocotb.test()
async def test_register_load(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    dut.uio_in.value = 0b000
    for byte_val in [0x78, 0x56, 0x34, 0x12]:
        dut.ui_in.value = byte_val
        await ClockCycles(dut.clk, 1)

    dut.uio_in.value = 0b010
    for byte_val in [0xEF, 0xBE, 0xAD, 0xDE]:
        dut.ui_in.value = byte_val
        await ClockCycles(dut.clk, 1)

    dut._log.info("register_load: passed")


@cocotb.test()
async def test_register_read(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_val_a = 0xDEADBEEF
    await load_register(dut, test_val_a, reg_sel=0)
    result_a = await read_register(dut, reg_sel=0)
    assert result_a == test_val_a, f"reg_a: expected {test_val_a:#x}, got {result_a:#x}"

    test_val_b = 0x12345678
    await load_register(dut, test_val_b, reg_sel=1)
    result_b = await read_register(dut, reg_sel=1)
    assert result_b == test_val_b, f"reg_b: expected {test_val_b:#x}, got {result_b:#x}"

    dut._log.info("register_read: passed")


@cocotb.test()
async def test_add(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        (0, 0, 0),
        (1, 1, 2),
        (P-1, 1, 0),
        (P-1, P-1, P-2),
        (0x12345678, 0x00000001, 0x12345679),
    ]

    for a, b, expected in test_cases:
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_opcode(dut, 0x1)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"add({a:#x}, {b:#x}): expected {expected:#x}, got {result:#x}"

    dut._log.info("add: passed")


@cocotb.test()
async def test_sub(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        (5, 3, 2),
        (3, 5, P-2),
        (0, 1, P-1),
        (P-1, P-1, 0),
        (0, 0, 0),
    ]

    for a, b, expected in test_cases:
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_opcode(dut, 0x2)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"sub({a:#x}, {b:#x}): expected {expected:#x}, got {result:#x}"

    dut._log.info("sub: passed")


@cocotb.test()
async def test_clr(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    await load_register(dut, 0xDEADBEEF, reg_sel=0)
    await load_register(dut, 0x12345678, reg_sel=1)

    result_a = await read_register(dut, reg_sel=0)
    result_b = await read_register(dut, reg_sel=1)
    assert result_a == 0xDEADBEEF
    assert result_b == 0x12345678

    await execute_opcode(dut, 0x4)

    result_a = await read_register(dut, reg_sel=0)
    result_b = await read_register(dut, reg_sel=1)
    assert result_a == 0, f"clr failed: reg_a = {result_a:#x}"
    assert result_b == 0, f"clr failed: reg_b = {result_b:#x}"

    dut._log.info("clr: passed")


@cocotb.test()
async def test_mul(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        (0, 12345, 0),
        (1, 12345, 12345),
        (2, 3, 6),
        (1000, 1000, 1000000),
        (P-1, 2, P-2),
        (0x10000, 0x10000, (0x10000 * 0x10000) % P),
        (12345, 67890, (12345 * 67890) % P),
    ]

    for a, b, expected in test_cases:
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_mul(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"mul({a:#x}, {b:#x}): expected {expected:#x}, got {result:#x}"

    dut._log.info("mul: passed")


@cocotb.test()
async def test_busy_timing(dut):
    clock = Clock(dut.clk, 10, units="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    await load_register(dut, 100, reg_sel=0)
    await load_register(dut, 200, reg_sel=1)

    dut.uio_in.value = 0x01
    dut.ui_in.value = 0x3
    await ClockCycles(dut.clk, 2)

    busy = int(dut.uio_out.value) & 0x01
    assert busy == 1, "BUSY should be high after MUL starts"

    cycle_count = 0
    while int(dut.uio_out.value) & 0x01:
        await ClockCycles(dut.clk, 1)
        cycle_count += 1
        assert cycle_count < 40, "BUSY stuck high"

    assert 30 <= cycle_count <= 32, f"expected ~31 cycles, got {cycle_count}"
    dut._log.info(f"busy_timing: passed ({cycle_count} cycles)")


@cocotb.test()
async def test_random_values(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    edge_cases = [0, 1, 2, P-1, P-2, 1<<15, 1<<20, 1<<25, 1<<30, (1<<16)-1, (1<<24)-1]

    # ADD random
    random.seed(42)
    for _ in range(100):
        a, b = random.randint(0, P-1), random.randint(0, P-1)
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_opcode(dut, 0x1)
        result = await read_register(dut, reg_sel=0)
        assert result == (a + b) % P

    # ADD edge cases
    for a in edge_cases:
        for b in edge_cases:
            await load_register(dut, a, reg_sel=0)
            await load_register(dut, b, reg_sel=1)
            await execute_opcode(dut, 0x1)
            result = await read_register(dut, reg_sel=0)
            assert result == (a + b) % P

    # SUB random
    random.seed(43)
    for _ in range(100):
        a, b = random.randint(0, P-1), random.randint(0, P-1)
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_opcode(dut, 0x2)
        result = await read_register(dut, reg_sel=0)
        assert result == (a - b) % P

    # SUB edge cases
    for a in edge_cases:
        for b in edge_cases:
            await load_register(dut, a, reg_sel=0)
            await load_register(dut, b, reg_sel=1)
            await execute_opcode(dut, 0x2)
            result = await read_register(dut, reg_sel=0)
            assert result == (a - b) % P

    # MUL random
    random.seed(44)
    for _ in range(100):
        a, b = random.randint(0, P-1), random.randint(0, P-1)
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_mul(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == (a * b) % P

    # MUL edge cases
    for a in edge_cases:
        for b in edge_cases:
            await load_register(dut, a, reg_sel=0)
            await load_register(dut, b, reg_sel=1)
            await execute_mul(dut)
            result = await read_register(dut, reg_sel=0)
            assert result == (a * b) % P

    dut._log.info("random_values: passed (663 cases)")


@cocotb.test()
async def test_chained_ops(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Chain: 5+3=8, 8*2=16, 16-1=15
    await load_register(dut, 5, reg_sel=0)
    await load_register(dut, 3, reg_sel=1)
    await execute_opcode(dut, 0x1)
    assert await read_register(dut, reg_sel=0) == 8

    await load_register(dut, 2, reg_sel=1)
    await execute_mul(dut)
    assert await read_register(dut, reg_sel=0) == 16

    await load_register(dut, 1, reg_sel=1)
    await execute_opcode(dut, 0x2)
    assert await read_register(dut, reg_sel=0) == 15

    # Chain ADDs: 10+5+5+5=25
    await execute_opcode(dut, 0x4)
    await load_register(dut, 10, reg_sel=0)
    await load_register(dut, 5, reg_sel=1)
    await execute_opcode(dut, 0x1)
    await execute_opcode(dut, 0x1)
    await execute_opcode(dut, 0x1)
    assert await read_register(dut, reg_sel=0) == 25

    # ((12+8)*3)-5 = 55
    await execute_opcode(dut, 0x4)
    await load_register(dut, 12, reg_sel=0)
    await load_register(dut, 8, reg_sel=1)
    await execute_opcode(dut, 0x1)
    await load_register(dut, 3, reg_sel=1)
    await execute_mul(dut)
    await load_register(dut, 5, reg_sel=1)
    await execute_opcode(dut, 0x2)
    assert await read_register(dut, reg_sel=0) == 55

    # Overflow: (P-1)+(P-1)=P-2, then *2
    await execute_opcode(dut, 0x4)
    await load_register(dut, P-1, reg_sel=0)
    await load_register(dut, P-1, reg_sel=1)
    await execute_opcode(dut, 0x1)
    assert await read_register(dut, reg_sel=0) == P-2
    await load_register(dut, 2, reg_sel=1)
    await execute_mul(dut)
    assert await read_register(dut, reg_sel=0) == ((P-2) * 2) % P

    dut._log.info("chained_ops: passed")


@cocotb.test()
async def test_nop_and_reserved(dut):
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_val_a = 0x12345678
    test_val_b = 0x5EADBEEF
    await load_register(dut, test_val_a, reg_sel=0)
    await load_register(dut, test_val_b, reg_sel=1)

    # NOP should not change registers
    await execute_opcode(dut, 0x0)
    assert await read_register(dut, reg_sel=0) == test_val_a
    assert await read_register(dut, reg_sel=1) == test_val_b
    assert (int(dut.uio_out.value) & 0x01) == 0

    # Reserved opcodes should act as NOP
    for opcode in range(0x5, 0x10):
        await execute_opcode(dut, opcode)
        assert await read_register(dut, reg_sel=0) == test_val_a
        assert await read_register(dut, reg_sel=1) == test_val_b

    # Operations still work after NOPs
    expected = (test_val_a + test_val_b) % P
    await execute_opcode(dut, 0x1)
    assert await read_register(dut, reg_sel=0) == expected

    dut._log.info("nop_and_reserved: passed")


@cocotb.test()
async def test_busy_protection(dut):
    clock = Clock(dut.clk, 10, units="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_a, test_b = 100, 200
    expected = (test_a * test_b) % P

    await load_register(dut, test_a, reg_sel=0)
    await load_register(dut, test_b, reg_sel=1)

    # Start MUL
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x3
    await ClockCycles(dut.clk, 2)
    assert (int(dut.uio_out.value) & 0x01) == 1

    # Try ADD during BUSY (should be ignored)
    await ClockCycles(dut.clk, 5)
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x1
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100
    assert (int(dut.uio_out.value) & 0x01) == 1

    # Try CLR during BUSY (should be ignored)
    await ClockCycles(dut.clk, 5)
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x4
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100
    assert (int(dut.uio_out.value) & 0x01) == 1

    # Try register load during BUSY (should be ignored)
    await ClockCycles(dut.clk, 5)
    dut.uio_in.value = 0b000
    dut.ui_in.value = 0xFF
    await ClockCycles(dut.clk, 4)
    dut.uio_in.value = 0b100

    # Wait for completion
    cycle_count = 0
    while int(dut.uio_out.value) & 0x01:
        await ClockCycles(dut.clk, 1)
        cycle_count += 1
        assert cycle_count < 40

    # Reset read counter and verify result
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x0
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100

    result_a = await read_register(dut, reg_sel=0)
    result_b = await read_register(dut, reg_sel=1)
    assert result_a == expected, f"expected {expected}, got {result_a}"
    assert result_b == test_b, f"reg_b corrupted: expected {test_b}, got {result_b}"

    # Verify normal operation after BUSY clears
    await load_register(dut, 1000, reg_sel=0)
    await load_register(dut, 2000, reg_sel=1)
    await execute_opcode(dut, 0x1)
    assert await read_register(dut, reg_sel=0) == 3000

    dut._log.info("busy_protection: passed")


@cocotb.test()
async def test_mul_boundary_cases(dut):
    """Test multiplication edge cases: power-of-two folding, max products."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # Zero cases
        (0x00000000, 0x00000000, 0x00000000, "0 * 0"),
        (0x00000000, 0x7FFFFFFE, 0x00000000, "0 * max"),
        (0x7FFFFFFE, 0x00000000, 0x00000000, "max * 0"),

        # Identity cases
        (0x00000001, 0x00000001, 0x00000001, "1 * 1"),
        (0x00000001, 0x7FFFFFFE, 0x7FFFFFFE, "1 * max"),
        (0x7FFFFFFE, 0x00000001, 0x7FFFFFFE, "max * 1"),

        # Power-of-two folding: 2^31 ≡ 1 (mod P)
        (0x40000000, 0x00000002, 0x00000001, "2^30 * 2 = 2^31 = 1"),
        (0x00008000, 0x00010000, 0x00000001, "2^15 * 2^16 = 2^31 = 1"),
        (0x40000000, 0x00000004, 0x00000002, "2^30 * 4 = 2^32 = 2"),
        (0x20000000, 0x00000004, 0x00000001, "2^29 * 4 = 2^31 = 1"),

        # 2^60 ≡ 2^29 (mod P) since 2^60 = 2^31 * 2^29 ≡ 1 * 2^29
        (0x40000000, 0x40000000, 0x20000000, "2^30 * 2^30 = 2^60 = 2^29"),

        # Maximum product: (P-1)^2 ≡ 1 (mod P) since (-1)^2 = 1
        (0x7FFFFFFE, 0x7FFFFFFE, 0x00000001, "(P-1)^2 = 1"),

        # (P-1) * small values: (P-1) ≡ -1, so (P-1)*n ≡ -n ≡ P-n
        (0x7FFFFFFE, 0x00000002, 0x7FFFFFFD, "(P-1)*2 = P-2"),
        (0x7FFFFFFE, 0x00000003, 0x7FFFFFFC, "(P-1)*3 = P-3"),

        # P value handling (P ≡ 0)
        (0x7FFFFFFF, 0x00000001, 0x00000000, "P * 1 = 0"),
        (0x7FFFFFFF, 0x7FFFFFFF, 0x00000000, "P * P = 0"),

        # Additional folding tests
        (0x55555555, 0x00000003, 0x00000001, "alternating bits * 3"),
        (0x60000000, 0x60000000, 0x48000000, "(3*2^29)^2 = 9*2^58"),
    ]

    for a, b, expected, desc in test_cases:
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_mul(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"mul {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("mul_boundary_cases: passed (17 cases)")


@cocotb.test()
async def test_add_boundary_cases(dut):
    """Test addition edge cases: carry folding, P→0 normalization."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # Identity
        (0x00000000, 0x00000000, 0x00000000, "0 + 0"),
        (0x12345678, 0x00000000, 0x12345678, "a + 0 = a"),
        (0x00000000, 0x12345678, 0x12345678, "0 + a = a"),

        # Sum exactly equals P (should become 0)
        (0x7FFFFFFE, 0x00000001, 0x00000000, "(P-1) + 1 = P = 0"),
        (0x3FFFFFFF, 0x40000000, 0x00000000, "sum = P exactly"),

        # Carry bit triggers (sum >= 2^31)
        (0x40000000, 0x40000000, 0x00000001, "2^30 + 2^30 = 2^31 = 1"),
        (0x40000001, 0x40000000, 0x00000002, "carry + 1 = 2"),
        (0x7FFFFFFE, 0x00000002, 0x00000001, "(P-1) + 2 = P + 1 = 1"),

        # Maximum values
        (0x7FFFFFFE, 0x7FFFFFFE, 0x7FFFFFFD, "(P-1) + (P-1) = P-2"),
        (0x7FFFFFFF, 0x7FFFFFFF, 0x00000000, "P + P = 0"),

        # Just below carry threshold
        (0x3FFFFFFF, 0x3FFFFFFF, 0x7FFFFFFE, "below carry"),

        # Additive inverse: a + (P-1-a) = P-1, a + (P-a) = 0
        (0x00000001, 0x7FFFFFFE, 0x00000000, "1 + (P-1) = 0"),
        (0x40000000, 0x3FFFFFFF, 0x00000000, "additive inverse"),
    ]

    for a, b, expected, desc in test_cases:
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_opcode(dut, 0x1)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"add {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("add_boundary_cases: passed (13 cases)")


@cocotb.test()
async def test_sub_boundary_cases(dut):
    """Test subtraction edge cases: underflow wrap-around."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # Identity
        (0x00000000, 0x00000000, 0x00000000, "0 - 0"),
        (0x12345678, 0x00000000, 0x12345678, "a - 0 = a"),
        (0x12345678, 0x12345678, 0x00000000, "a - a = 0"),

        # No underflow
        (0x00000005, 0x00000003, 0x00000002, "5 - 3 = 2"),
        (0x7FFFFFFE, 0x00000001, 0x7FFFFFFD, "max - 1"),

        # Underflow (a < b)
        (0x00000000, 0x00000001, 0x7FFFFFFE, "0 - 1 = P-1"),
        (0x00000003, 0x00000005, 0x7FFFFFFD, "3 - 5 = P-2"),
        (0x00000000, 0x7FFFFFFE, 0x00000001, "0 - (P-1) = 1"),
        (0x00000001, 0x7FFFFFFE, 0x00000002, "1 - (P-1) = 2"),

        # Boundary at 2^30
        (0x40000000, 0x40000000, 0x00000000, "2^30 - 2^30 = 0"),
        (0x3FFFFFFF, 0x40000000, 0x7FFFFFFE, "underflow at mid"),
        (0x40000001, 0x40000000, 0x00000001, "no underflow at mid"),

        # Maximum values
        (0x7FFFFFFE, 0x7FFFFFFE, 0x00000000, "max - max = 0"),
    ]

    for a, b, expected, desc in test_cases:
        await load_register(dut, a, reg_sel=0)
        await load_register(dut, b, reg_sel=1)
        await execute_opcode(dut, 0x2)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"sub {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("sub_boundary_cases: passed (13 cases)")


@cocotb.test()
async def test_reg_preservation(dut):
    """Verify reg_b is preserved after ADD, SUB, and MUL operations."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_b = 0x12345678

    # Test ADD preserves reg_b
    await load_register(dut, 100, reg_sel=0)
    await load_register(dut, test_b, reg_sel=1)
    await execute_opcode(dut, 0x1)
    result_b = await read_register(dut, reg_sel=1)
    assert result_b == test_b, f"ADD corrupted reg_b: expected {test_b:#x}, got {result_b:#x}"

    # Test SUB preserves reg_b
    await load_register(dut, 200, reg_sel=0)
    await execute_opcode(dut, 0x2)
    result_b = await read_register(dut, reg_sel=1)
    assert result_b == test_b, f"SUB corrupted reg_b: expected {test_b:#x}, got {result_b:#x}"

    # Test MUL preserves reg_b
    await load_register(dut, 300, reg_sel=0)
    await execute_mul(dut)
    result_b = await read_register(dut, reg_sel=1)
    assert result_b == test_b, f"MUL corrupted reg_b: expected {test_b:#x}, got {result_b:#x}"

    # Test multiple chained operations preserve reg_b
    await load_register(dut, 50, reg_sel=0)
    await execute_opcode(dut, 0x1)
    await execute_opcode(dut, 0x1)
    await execute_opcode(dut, 0x2)
    await execute_mul(dut)
    result_b = await read_register(dut, reg_sel=1)
    assert result_b == test_b, f"Chained ops corrupted reg_b"

    dut._log.info("reg_preservation: passed")


@cocotb.test()
async def test_back_to_back_mul(dut):
    """Test sequential multiplication operations."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # First MUL: 5 * 7 = 35
    await load_register(dut, 5, reg_sel=0)
    await load_register(dut, 7, reg_sel=1)
    await execute_mul(dut)
    result = await read_register(dut, reg_sel=0)
    assert result == 35, f"first mul: expected 35, got {result}"

    # Second MUL immediately: 35 * 2 = 70
    await load_register(dut, 2, reg_sel=1)
    await execute_mul(dut)
    result = await read_register(dut, reg_sel=0)
    assert result == 70, f"second mul: expected 70, got {result}"

    # Third MUL: 70 * 10 = 700
    await load_register(dut, 10, reg_sel=1)
    await execute_mul(dut)
    result = await read_register(dut, reg_sel=0)
    assert result == 700, f"third mul: expected 700, got {result}"

    # Fourth MUL with large value: test overflow
    await load_register(dut, P-1, reg_sel=0)
    await load_register(dut, P-1, reg_sel=1)
    await execute_mul(dut)
    result = await read_register(dut, reg_sel=0)
    assert result == 1, f"max*max mul: expected 1, got {result}"

    # Another MUL right after: 1 * 12345 = 12345
    await load_register(dut, 12345, reg_sel=1)
    await execute_mul(dut)
    result = await read_register(dut, reg_sel=0)
    assert result == 12345, f"follow-up mul: expected 12345, got {result}"

    dut._log.info("back_to_back_mul: passed")


@cocotb.test()
async def test_read_counter_wrap(dut):
    """Test read counter wraps correctly after 4+ consecutive reads."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_val = 0x04030201
    await load_register(dut, test_val, reg_sel=0)

    # Read 8 consecutive bytes (should wrap after 4)
    dut.uio_in.value = 0b100  # RW=1, REG_SEL=0
    expected_bytes = [0x01, 0x02, 0x03, 0x04, 0x01, 0x02, 0x03, 0x04]

    for i, expected in enumerate(expected_bytes):
        await ClockCycles(dut.clk, 1)
        byte_val = int(dut.uo_out.value)
        assert byte_val == expected, f"byte {i}: expected {expected:#x}, got {byte_val:#x}"

    dut._log.info("read_counter_wrap: passed")


@cocotb.test()
async def test_reset_during_mul(dut):
    """Test reset during multiplication clears state properly."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Load values and start MUL
    await load_register(dut, 12345, reg_sel=0)
    await load_register(dut, 67890, reg_sel=1)

    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x3
    await ClockCycles(dut.clk, 2)

    # Verify MUL is in progress
    assert (int(dut.uio_out.value) & 0x01) == 1, "BUSY should be high"

    # Wait a few cycles then reset mid-operation
    await ClockCycles(dut.clk, 10)
    assert (int(dut.uio_out.value) & 0x01) == 1, "BUSY should still be high"

    # Assert reset - also clear control signals to avoid re-triggering MUL
    dut.uio_in.value = 0b100  # Clear CMD_EN before reset to avoid re-trigger
    dut.ui_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)

    # Release reset
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    # BUSY should be low after reset
    busy = int(dut.uio_out.value) & 0x01
    assert busy == 0, f"BUSY should be low after reset, got {busy}"

    # Registers should be cleared
    result_a = await read_register(dut, reg_sel=0)
    result_b = await read_register(dut, reg_sel=1)
    assert result_a == 0, f"reg_a not cleared: {result_a:#x}"
    assert result_b == 0, f"reg_b not cleared: {result_b:#x}"

    # Normal operation should work after reset
    await load_register(dut, 100, reg_sel=0)
    await load_register(dut, 200, reg_sel=1)
    await execute_opcode(dut, 0x1)
    result = await read_register(dut, reg_sel=0)
    assert result == 300, f"post-reset operation failed: expected 300, got {result}"

    dut._log.info("reset_during_mul: passed")


@cocotb.test()
async def test_mathematical_identities(dut):
    """Verify mathematical field properties hold."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Commutativity of addition: a + b = b + a
    a, b = 0x12345678, 0x23456789
    await load_register(dut, a, reg_sel=0)
    await load_register(dut, b, reg_sel=1)
    await execute_opcode(dut, 0x1)
    result1 = await read_register(dut, reg_sel=0)

    await load_register(dut, b, reg_sel=0)
    await load_register(dut, a, reg_sel=1)
    await execute_opcode(dut, 0x1)
    result2 = await read_register(dut, reg_sel=0)
    assert result1 == result2, f"add commutativity failed: {result1:#x} != {result2:#x}"

    # Commutativity of multiplication: a * b = b * a
    a, b = 12345, 67890
    await load_register(dut, a, reg_sel=0)
    await load_register(dut, b, reg_sel=1)
    await execute_mul(dut)
    result1 = await read_register(dut, reg_sel=0)

    await load_register(dut, b, reg_sel=0)
    await load_register(dut, a, reg_sel=1)
    await execute_mul(dut)
    result2 = await read_register(dut, reg_sel=0)
    assert result1 == result2, f"mul commutativity failed: {result1} != {result2}"

    # Distributive property: a * (b + c) = a*b + a*c
    a, b, c = 7, 11, 13
    # Calculate a * (b + c)
    await load_register(dut, b, reg_sel=0)
    await load_register(dut, c, reg_sel=1)
    await execute_opcode(dut, 0x1)  # b + c
    await load_register(dut, a, reg_sel=1)
    # Swap: need a in reg_a, (b+c) in reg_b
    sum_bc = await read_register(dut, reg_sel=0)
    await load_register(dut, a, reg_sel=0)
    await load_register(dut, sum_bc, reg_sel=1)
    await execute_mul(dut)
    result_lhs = await read_register(dut, reg_sel=0)

    # Calculate a*b + a*c
    await load_register(dut, a, reg_sel=0)
    await load_register(dut, b, reg_sel=1)
    await execute_mul(dut)
    ab = await read_register(dut, reg_sel=0)

    await load_register(dut, a, reg_sel=0)
    await load_register(dut, c, reg_sel=1)
    await execute_mul(dut)
    ac = await read_register(dut, reg_sel=0)

    await load_register(dut, ab, reg_sel=0)
    await load_register(dut, ac, reg_sel=1)
    await execute_opcode(dut, 0x1)
    result_rhs = await read_register(dut, reg_sel=0)

    assert result_lhs == result_rhs, f"distributive failed: {result_lhs} != {result_rhs}"

    # Multiplicative inverse test: (P-1) * (P-1) = 1 (since -1 * -1 = 1)
    await load_register(dut, P-1, reg_sel=0)
    await load_register(dut, P-1, reg_sel=1)
    await execute_mul(dut)
    result = await read_register(dut, reg_sel=0)
    assert result == 1, f"(-1)^2 should be 1, got {result}"

    dut._log.info("mathematical_identities: passed")
