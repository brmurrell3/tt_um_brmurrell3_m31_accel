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
    # reg_sel encoding: uio_in[3]=REG_SEL[1], uio_in[1]=REG_SEL[0], uio_in[2]=RW, uio_in[0]=CMD_EN
    # For write: RW=0, CMD_EN=0
    # reg_sel=0: uio_in = 0b0000 (reg_a)
    # reg_sel=1: uio_in = 0b0010 (reg_b)
    # reg_sel=2: uio_in = 0b1000 (reg_c)
    uio_val = ((reg_sel & 2) << 2) | ((reg_sel & 1) << 1)
    dut.uio_in.value = uio_val
    dut.ui_in.value = 0
    for i in range(4):
        byte_val = (value >> (i * 8)) & 0xFF
        dut.ui_in.value = byte_val
        await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100  # RW=1 to stop loading
    dut.ui_in.value = 0


async def read_register(dut, reg_sel):
    # reg_sel encoding: uio_in[3]=REG_SEL[1], uio_in[1]=REG_SEL[0], uio_in[2]=RW, uio_in[0]=CMD_EN
    # For read: RW=1 (bit 2), CMD_EN=0 (bit 0)
    # reg_sel=0: uio_in = 0b0100 (reg_a)
    # reg_sel=1: uio_in = 0b0110 (reg_b)
    # reg_sel=2: uio_in = 0b1100 (reg_c)
    uio_val = ((reg_sel & 2) << 2) | ((reg_sel & 1) << 1) | 0b100
    dut.uio_in.value = uio_val
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
    clock = Clock(dut.clk, 10, unit="us")
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
    clock = Clock(dut.clk, 10, unit="us")
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


async def execute_mac(dut):
    """Execute MAC operation and wait for completion."""
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x5  # MAC opcode
    await ClockCycles(dut.clk, 2)
    dut.ui_in.value = 0x0
    cycle_count = 0
    while int(dut.uio_out.value) & 0x01:
        await ClockCycles(dut.clk, 1)
        cycle_count += 1
        assert cycle_count < 40, "BUSY stuck high during MAC"
    dut.uio_in.value = 0b100
    return cycle_count


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


# ============================================================================
# MAC (Multiply-Accumulate) Tests
# MAC operation: reg_a = reg_a + (reg_b × reg_c) mod P
# reg_c is accessed via reg_sel = 2'b10 (uio_in[3]=1, uio_in[1]=0)
# ============================================================================


@cocotb.test()
async def test_mac_basic(dut):
    """Test basic MAC: 0 + (a × b) = a × b when reg_a starts at 0."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # (reg_a, reg_b, reg_c, expected_result, description)
        (0, 2, 3, 6, "0 + 2*3 = 6"),
        (0, 10, 10, 100, "0 + 10*10 = 100"),
        (0, 1000, 1000, 1000000, "0 + 1000*1000 = 1000000"),
        (0, 12345, 67890, (12345 * 67890) % P, "0 + 12345*67890"),
        (0, 0x10000, 0x10000, (0x10000 * 0x10000) % P, "0 + 2^16 * 2^16"),
        (0, P-1, 2, P-2, "0 + (P-1)*2 = P-2"),
        (0, P-1, P-1, 1, "0 + (P-1)*(P-1) = 1"),
        (0, 0x40000000, 2, 1, "0 + 2^30*2 = 2^31 = 1 mod P"),
    ]

    for reg_a, reg_b, reg_c, expected, desc in test_cases:
        await load_register(dut, reg_a, reg_sel=0)  # reg_a
        await load_register(dut, reg_b, reg_sel=1)  # reg_b
        await load_register(dut, reg_c, reg_sel=2)  # reg_c
        await execute_mac(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"MAC {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("mac_basic: passed (8 test vectors)")


@cocotb.test()
async def test_mac_accumulation(dut):
    """Test MAC with non-zero reg_a: accumulation behavior."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # (reg_a, reg_b, reg_c, expected = reg_a + reg_b*reg_c mod P)
        (10, 2, 3, 16, "10 + 2*3 = 16"),
        (100, 5, 7, 135, "100 + 5*7 = 135"),
        (500, 10, 20, 700, "500 + 10*20 = 700"),
        (1000000, 1000, 1000, 2000000, "1M + 1K*1K = 2M"),
        (P-10, 5, 3, (P-10+15) % P, "P-10 + 5*3 wraps"),  # Fixed: P-10+15 > P, so wraps to 5
        (P-1, 1, 1, 0, "(P-1) + 1*1 = P = 0"),
        (P-2, 1, 2, 0, "(P-2) + 1*2 = P = 0"),
        (P-5, 2, 3, 1, "(P-5) + 2*3 = P+1 = 1"),
        (0x12345678, 0x100, 0x100, (0x12345678 + 0x10000) % P, "accum with 16-bit product"),
        (P-1, P-1, P-1, 0, "(P-1) + (P-1)*(P-1) = (P-1) + 1 = P = 0"),
    ]

    for reg_a, reg_b, reg_c, expected, desc in test_cases:
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)
        await execute_mac(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"MAC accum {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("mac_accumulation: passed (10 test vectors)")


@cocotb.test()
async def test_mac_identity_cases(dut):
    """Test MAC identity cases: a + (1 × b) = a + b, a + (0 × b) = a."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_values = [0, 1, 2, 100, 12345, 0x12345678, P-1, P-2, 0x40000000]

    # Test a + (1 × b) = a + b (identity multiplication)
    for a in test_values[:5]:
        for b in test_values[:5]:
            expected = (a + b) % P
            await load_register(dut, a, reg_sel=0)
            await load_register(dut, 1, reg_sel=1)  # multiplier = 1
            await load_register(dut, b, reg_sel=2)  # multiplicand = b
            await execute_mac(dut)
            result = await read_register(dut, reg_sel=0)
            assert result == expected, f"a + 1*b: a={a}, b={b}: expected {expected}, got {result}"

    # Test a + (0 × b) = a (zero multiplication)
    for a in test_values:
        for b in test_values[:3]:
            expected = a % P  # No change since 0 × b = 0
            if expected == P:
                expected = 0
            await load_register(dut, a, reg_sel=0)
            await load_register(dut, 0, reg_sel=1)  # multiplier = 0
            await load_register(dut, b, reg_sel=2)  # multiplicand = b
            await execute_mac(dut)
            result = await read_register(dut, reg_sel=0)
            assert result == expected, f"a + 0*b: a={a}, b={b}: expected {expected}, got {result}"

    # Test a + (b × 0) = a (zero multiplication, other operand)
    for a in test_values:
        for b in test_values[:3]:
            expected = a % P
            if expected == P:
                expected = 0
            await load_register(dut, a, reg_sel=0)
            await load_register(dut, b, reg_sel=1)  # multiplier = b
            await load_register(dut, 0, reg_sel=2)  # multiplicand = 0
            await execute_mac(dut)
            result = await read_register(dut, reg_sel=0)
            assert result == expected, f"a + b*0: a={a}, b={b}: expected {expected}, got {result}"

    dut._log.info("mac_identity_cases: passed (79 test vectors)")


@cocotb.test()
async def test_mac_dot_product(dut):
    """Test chained MAC for dot product: Σ(ai × bi) using 4+ terms."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Dot product test case 1: Simple integers
    # [1, 2, 3, 4] · [5, 6, 7, 8] = 1*5 + 2*6 + 3*7 + 4*8 = 5 + 12 + 21 + 32 = 70
    a_vec = [1, 2, 3, 4]
    b_vec = [5, 6, 7, 8]
    expected = sum(a * b for a, b in zip(a_vec, b_vec)) % P
    assert expected == 70

    await load_register(dut, 0, reg_sel=0)  # Initialize accumulator to 0
    for a_i, b_i in zip(a_vec, b_vec):
        await load_register(dut, a_i, reg_sel=1)
        await load_register(dut, b_i, reg_sel=2)
        await execute_mac(dut)

    result = await read_register(dut, reg_sel=0)
    assert result == expected, f"dot product 1: expected {expected}, got {result}"

    # Dot product test case 2: Larger values
    # [100, 200, 300, 400] · [10, 20, 30, 40] = 1000 + 4000 + 9000 + 16000 = 30000
    a_vec = [100, 200, 300, 400]
    b_vec = [10, 20, 30, 40]
    expected = sum(a * b for a, b in zip(a_vec, b_vec)) % P
    assert expected == 30000

    await load_register(dut, 0, reg_sel=0)
    for a_i, b_i in zip(a_vec, b_vec):
        await load_register(dut, a_i, reg_sel=1)
        await load_register(dut, b_i, reg_sel=2)
        await execute_mac(dut)

    result = await read_register(dut, reg_sel=0)
    assert result == expected, f"dot product 2: expected {expected}, got {result}"

    # Dot product test case 3: 8 terms with overflow potential
    a_vec = [0x10000, 0x20000, 0x30000, 0x40000, 0x50000, 0x60000, 0x70000, 0x80000]
    b_vec = [0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700, 0x800]
    expected = sum(a * b for a, b in zip(a_vec, b_vec)) % P

    await load_register(dut, 0, reg_sel=0)
    for a_i, b_i in zip(a_vec, b_vec):
        await load_register(dut, a_i, reg_sel=1)
        await load_register(dut, b_i, reg_sel=2)
        await execute_mac(dut)

    result = await read_register(dut, reg_sel=0)
    assert result == expected, f"dot product 3: expected {expected:#x}, got {result:#x}"

    # Dot product test case 4: Values near P-1
    a_vec = [P-1, P-2, P-3, P-4]
    b_vec = [1, 2, 3, 4]
    # (P-1)*1 + (P-2)*2 + (P-3)*3 + (P-4)*4 mod P
    # = (-1)*1 + (-2)*2 + (-3)*3 + (-4)*4 mod P
    # = -1 - 4 - 9 - 16 = -30 = P - 30
    expected = sum(a * b for a, b in zip(a_vec, b_vec)) % P

    await load_register(dut, 0, reg_sel=0)
    for a_i, b_i in zip(a_vec, b_vec):
        await load_register(dut, a_i, reg_sel=1)
        await load_register(dut, b_i, reg_sel=2)
        await execute_mac(dut)

    result = await read_register(dut, reg_sel=0)
    assert result == expected, f"dot product 4: expected {expected:#x}, got {result:#x}"

    dut._log.info("mac_dot_product: passed (4 dot products, 24 MAC operations)")


@cocotb.test()
async def test_mac_overflow_handling(dut):
    """Test MAC overflow handling: values near P-1 that wrap around."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # Cases where product overflows 31 bits
        (0, 0x40000000, 4, 2, "0 + 2^30*4 = 2^32 = 2"),
        (P-1, 0x40000000, 4, 1, "(P-1) + 2^32 = (P-1) + 2 = P+1 = 1"),

        # Cases where accumulation causes overflow
        (P-1, 1, 2, 1, "(P-1) + 1*2 = P+1 = 1"),
        (P-2, 1, 3, 1, "(P-2) + 1*3 = P+1 = 1"),
        (P-100, 10, 11, 10, "(P-100) + 10*11 = P+10 = 10"),

        # Product is P-1, accumulation pushes to P
        (1, 1, P-1, 0, "1 + 1*(P-1) = P = 0"),

        # Large product with large accumulator
        (P-1, P-1, P-1, 0, "(P-1) + (P-1)*(P-1) = (P-1) + 1 = P = 0"),
        (P-2, P-1, P-1, P-1, "(P-2) + 1 = P-1"),

        # Near maximum accumulation
        (0x7FFFFFD0, 0, 1, 0x7FFFFFD0, "large accum + 0"),
        (0x7FFFFFD0, 1, 0x2E, 0x7FFFFFFE, "large accum + small = P-1"),
        (0x7FFFFFD0, 1, 0x2F, 0, "large accum + small = P = 0"),
        (0x7FFFFFD0, 1, 0x30, 1, "large accum + small = P+1 = 1"),

        # Both product and sum wrap
        (0x40000000, 0x40000000, 0x40000000, 0x60000000, "2^30 + 2^30*2^30 = 2^30 + 2^29 = 3*2^29"),
    ]

    for reg_a, reg_b, reg_c, expected, desc in test_cases:
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)
        await execute_mac(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"MAC overflow {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("mac_overflow_handling: passed (13 test vectors)")


@cocotb.test()
async def test_mac_operand_preservation(dut):
    """Verify reg_b and reg_c are unchanged after MAC operation."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_configs = [
        (0, 0x12345678, 0x5EADBEEF),
        (100, 200, 300),
        (P-1, P-2, P-3),
        (0x40000000, 0x30000000, 0x20000000),
        (1, 1, 1),
        (0, P-1, P-1),
    ]

    for reg_a, reg_b, reg_c in test_configs:
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)

        await execute_mac(dut)

        # Verify reg_b is preserved
        result_b = await read_register(dut, reg_sel=1)
        assert result_b == reg_b, f"MAC corrupted reg_b: expected {reg_b:#x}, got {result_b:#x}"

        # Verify reg_c is preserved
        result_c = await read_register(dut, reg_sel=2)
        assert result_c == reg_c, f"MAC corrupted reg_c: expected {reg_c:#x}, got {result_c:#x}"

    # Test preservation across multiple chained MAC operations
    await load_register(dut, 0, reg_sel=0)
    await load_register(dut, 100, reg_sel=1)
    await load_register(dut, 200, reg_sel=2)

    for i in range(5):
        await execute_mac(dut)
        result_b = await read_register(dut, reg_sel=1)
        result_c = await read_register(dut, reg_sel=2)
        assert result_b == 100, f"chained MAC {i} corrupted reg_b"
        assert result_c == 200, f"chained MAC {i} corrupted reg_c"

    # Final accumulator value: 0 + 5 * (100 * 200) = 100000
    result_a = await read_register(dut, reg_sel=0)
    expected = (5 * 100 * 200) % P
    assert result_a == expected, f"chained MAC result: expected {expected}, got {result_a}"

    dut._log.info("mac_operand_preservation: passed (11 MAC operations verified)")


@cocotb.test()
async def test_mac_busy_timing(dut):
    """Test BUSY signal timing for MAC (should be 31 cycles like MUL)."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # Test with non-zero values to ensure timing is consistent
    test_values = [
        (0, 100, 200),
        (100, 200, 300),
        (12345, 67890, 11111),
    ]

    for reg_a, reg_b, reg_c in test_values:
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)

        # Use execute_mac helper which handles timing correctly
        cycle_count = await execute_mac(dut)

        # Should be approximately 31 cycles (same as MUL)
        # The execute_mac waits 2 cycles before counting, so we expect ~29-30
        assert 28 <= cycle_count <= 32, f"MAC timing: expected ~30 cycles, got {cycle_count}"

    dut._log.info("mac_busy_timing: passed (3 timing tests)")


@cocotb.test()
async def test_mac_edge_cases(dut):
    """Test MAC edge cases: P-1 values, zero multiplication, maximum accumulation."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_cases = [
        # P-1 as reg_a (represents -1 mod P)
        (P-1, 2, 3, (P-1 + 6) % P, "(P-1) + 2*3 = 5"),
        (P-1, 0, 0, P-1, "(P-1) + 0*0 = P-1"),
        (P-1, 1, 0, P-1, "(P-1) + 1*0 = P-1"),
        (P-1, 0, 1, P-1, "(P-1) + 0*1 = P-1"),

        # P-1 as multiplier/multiplicand
        (0, P-1, 1, P-1, "0 + (P-1)*1 = P-1"),
        (0, 1, P-1, P-1, "0 + 1*(P-1) = P-1"),
        (0, P-1, 2, P-2, "0 + (P-1)*2 = P-2"),
        (0, 2, P-1, P-2, "0 + 2*(P-1) = P-2"),

        # All operands are P-1
        (P-1, P-1, P-1, 0, "(P-1) + (P-1)*(P-1) = (P-1) + 1 = 0"),

        # Zero multiplication variants
        (12345, 0, 99999, 12345, "a + 0*c = a"),
        (12345, 99999, 0, 12345, "a + b*0 = a"),
        (0, 0, 0, 0, "0 + 0*0 = 0"),

        # Maximum accumulation tests
        (P-1, 0, P-1, P-1, "(P-1) + 0*(P-1) = P-1"),
        (0, P-1, P-1, 1, "0 + (P-1)*(P-1) = 1"),

        # Power of 2 edge cases (2^31 ≡ 1 mod P)
        (0, 0x40000000, 2, 1, "0 + 2^30*2 = 2^31 = 1"),
        (P-1, 0x40000000, 2, 0, "(P-1) + 1 = P = 0"),
        (0, 0x20000000, 4, 1, "0 + 2^29*4 = 2^31 = 1"),

        # Alternating bit patterns
        (0, 0x55555555, 3, 0x55555555 * 3 % P, "alternating bits * 3"),
        (0, 0x2AAAAAAA, 3, 0x2AAAAAAA * 3 % P, "alternating bits variant"),

        # Single bit values
        (0, 1, 1, 1, "0 + 1*1 = 1"),
        (1, 1, 1, 2, "1 + 1*1 = 2"),
        (P-2, 1, 1, P-1, "(P-2) + 1 = P-1"),

        # Product equals P (should become 0)
        (0, 0x7FFFFFFF, 1, 0, "0 + P*1 = 0"),
        (0, 1, 0x7FFFFFFF, 0, "0 + 1*P = 0"),
        (5, 0x7FFFFFFF, 0x7FFFFFFF, 5, "5 + P*P = 5 + 0 = 5"),
    ]

    for reg_a, reg_b, reg_c, expected, desc in test_cases:
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)
        await execute_mac(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"MAC edge {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("mac_edge_cases: passed (25 test vectors)")


@cocotb.test()
async def test_mac_vs_mul_add(dut):
    """Verify MAC produces same result as separate MUL then ADD."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    random.seed(123)
    test_cases = []

    # Generate random test cases
    for _ in range(20):
        reg_a = random.randint(0, P-1)
        reg_b = random.randint(0, P-1)
        reg_c = random.randint(0, P-1)
        test_cases.append((reg_a, reg_b, reg_c))

    # Add some edge cases
    test_cases.extend([
        (0, 0, 0),
        (P-1, P-1, P-1),
        (1, 2, 3),
        (0x40000000, 0x40000000, 0x40000000),
        (P-1, 1, 1),
        (0, P-1, 2),
        (100, 200, 300),
        (0x12345678, 0x23456789, 0x3456789A % P),
    ])

    for reg_a, reg_b, reg_c in test_cases:
        # Method 1: Use MAC directly
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)
        await execute_mac(dut)
        mac_result = await read_register(dut, reg_sel=0)

        # Method 2: Use MUL then ADD
        # First compute reg_b * reg_c using MUL
        await load_register(dut, reg_b, reg_sel=0)
        await load_register(dut, reg_c, reg_sel=1)
        await execute_mul(dut)
        product = await read_register(dut, reg_sel=0)

        # Then add reg_a to the product
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, product, reg_sel=1)
        await execute_opcode(dut, 0x1)  # ADD
        mul_add_result = await read_register(dut, reg_sel=0)

        assert mac_result == mul_add_result, \
            f"MAC != MUL+ADD: a={reg_a:#x}, b={reg_b:#x}, c={reg_c:#x}: " \
            f"MAC={mac_result:#x}, MUL+ADD={mul_add_result:#x}"

    dut._log.info("mac_vs_mul_add: passed (28 comparison tests)")


@cocotb.test()
async def test_mac_random_values(dut):
    """Test MAC with random values across the valid range."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    random.seed(456)

    # Random tests
    for i in range(50):
        reg_a = random.randint(0, P-1)
        reg_b = random.randint(0, P-1)
        reg_c = random.randint(0, P-1)
        expected = (reg_a + (reg_b * reg_c) % P) % P

        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)
        await execute_mac(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, \
            f"MAC random {i}: a={reg_a:#x}, b={reg_b:#x}, c={reg_c:#x}: " \
            f"expected {expected:#x}, got {result:#x}"

    # Edge case grid: test combinations of special values
    edge_values = [0, 1, 2, P-1, P-2, 0x40000000, 0x20000000, 0x7FFFFFFF]
    test_count = 0
    for a in edge_values[:4]:
        for b in edge_values[:4]:
            for c in edge_values[:4]:
                expected = (a + (b * c) % P) % P
                await load_register(dut, a, reg_sel=0)
                await load_register(dut, b, reg_sel=1)
                await load_register(dut, c, reg_sel=2)
                await execute_mac(dut)
                result = await read_register(dut, reg_sel=0)
                assert result == expected, \
                    f"MAC edge grid: a={a:#x}, b={b:#x}, c={c:#x}: " \
                    f"expected {expected:#x}, got {result:#x}"
                test_count += 1

    dut._log.info(f"mac_random_values: passed (50 random + {test_count} edge grid = {50 + test_count} tests)")


@cocotb.test()
async def test_mac_reg_c_load_and_read(dut):
    """Test loading and reading reg_c independently."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_values = [
        0x00000000,
        0x00000001,
        0x7FFFFFFE,  # P-1
        0x7FFFFFFF,  # P
        0x12345678,
        0x5EADBEEF,
        0x40000000,  # 2^30
        0x3FFFFFFF,  # 2^30 - 1
    ]

    for val in test_values:
        await load_register(dut, val, reg_sel=2)  # Load to reg_c
        result = await read_register(dut, reg_sel=2)  # Read from reg_c
        assert result == val, f"reg_c load/read: expected {val:#x}, got {result:#x}"

    # Test that reg_c is independent of reg_a and reg_b
    await load_register(dut, 0x11111111, reg_sel=0)
    await load_register(dut, 0x22222222, reg_sel=1)
    await load_register(dut, 0x33333333, reg_sel=2)

    assert await read_register(dut, reg_sel=0) == 0x11111111
    assert await read_register(dut, reg_sel=1) == 0x22222222
    assert await read_register(dut, reg_sel=2) == 0x33333333

    # Modify one register and verify others unchanged
    await load_register(dut, 0xAAAAAAAA, reg_sel=0)
    assert await read_register(dut, reg_sel=0) == 0xAAAAAAAA
    assert await read_register(dut, reg_sel=1) == 0x22222222
    assert await read_register(dut, reg_sel=2) == 0x33333333

    await load_register(dut, 0xBBBBBBBB, reg_sel=1)
    assert await read_register(dut, reg_sel=0) == 0xAAAAAAAA
    assert await read_register(dut, reg_sel=1) == 0xBBBBBBBB
    assert await read_register(dut, reg_sel=2) == 0x33333333

    await load_register(dut, 0xCCCCCCCC, reg_sel=2)
    assert await read_register(dut, reg_sel=0) == 0xAAAAAAAA
    assert await read_register(dut, reg_sel=1) == 0xBBBBBBBB
    assert await read_register(dut, reg_sel=2) == 0xCCCCCCCC

    dut._log.info("mac_reg_c_load_and_read: passed (8 load/read + 9 independence checks)")


@cocotb.test()
async def test_mac_busy_protection(dut):
    """Test that operations during MAC BUSY are ignored."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    test_a, test_b, test_c = 100, 200, 300
    expected = (test_a + (test_b * test_c) % P) % P

    await load_register(dut, test_a, reg_sel=0)
    await load_register(dut, test_b, reg_sel=1)
    await load_register(dut, test_c, reg_sel=2)

    # Start MAC
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x5  # MAC opcode
    await ClockCycles(dut.clk, 2)
    assert (int(dut.uio_out.value) & 0x01) == 1, "BUSY should be high"

    # Try ADD during BUSY (should be ignored)
    await ClockCycles(dut.clk, 5)
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x1  # ADD opcode
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100
    assert (int(dut.uio_out.value) & 0x01) == 1

    # Try CLR during BUSY (should be ignored)
    await ClockCycles(dut.clk, 5)
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x4  # CLR opcode
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100
    assert (int(dut.uio_out.value) & 0x01) == 1

    # Try another MAC during BUSY (should be ignored)
    await ClockCycles(dut.clk, 3)
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x5  # MAC opcode
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100
    assert (int(dut.uio_out.value) & 0x01) == 1

    # Try register load during BUSY (should be ignored)
    await ClockCycles(dut.clk, 3)
    dut.uio_in.value = 0b000  # Load reg_a
    dut.ui_in.value = 0xFF
    await ClockCycles(dut.clk, 4)
    dut.uio_in.value = 0b100

    # Wait for completion
    cycle_count = 0
    while int(dut.uio_out.value) & 0x01:
        await ClockCycles(dut.clk, 1)
        cycle_count += 1
        assert cycle_count < 40

    # Reset read counter
    dut.uio_in.value = 0b001
    dut.ui_in.value = 0x0  # NOP
    await ClockCycles(dut.clk, 1)
    dut.uio_in.value = 0b100

    # Verify MAC completed correctly despite interference attempts
    result_a = await read_register(dut, reg_sel=0)
    result_b = await read_register(dut, reg_sel=1)
    result_c = await read_register(dut, reg_sel=2)

    assert result_a == expected, f"MAC result: expected {expected}, got {result_a}"
    assert result_b == test_b, f"reg_b corrupted: expected {test_b}, got {result_b}"
    assert result_c == test_c, f"reg_c corrupted: expected {test_c}, got {result_c}"

    dut._log.info("mac_busy_protection: passed")


@cocotb.test()
async def test_mac_after_other_ops(dut):
    """Test MAC works correctly after other operations."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # ADD then MAC
    await load_register(dut, 10, reg_sel=0)
    await load_register(dut, 5, reg_sel=1)
    await execute_opcode(dut, 0x1)  # 10 + 5 = 15
    await load_register(dut, 2, reg_sel=1)
    await load_register(dut, 3, reg_sel=2)
    await execute_mac(dut)  # 15 + 2*3 = 21
    assert await read_register(dut, reg_sel=0) == 21

    # SUB then MAC
    await load_register(dut, 100, reg_sel=0)
    await load_register(dut, 30, reg_sel=1)
    await execute_opcode(dut, 0x2)  # 100 - 30 = 70
    await load_register(dut, 10, reg_sel=1)
    await load_register(dut, 3, reg_sel=2)
    await execute_mac(dut)  # 70 + 10*3 = 100
    assert await read_register(dut, reg_sel=0) == 100

    # MUL then MAC
    await load_register(dut, 5, reg_sel=0)
    await load_register(dut, 6, reg_sel=1)
    await execute_mul(dut)  # 5 * 6 = 30
    await load_register(dut, 7, reg_sel=1)
    await load_register(dut, 2, reg_sel=2)
    await execute_mac(dut)  # 30 + 7*2 = 44
    assert await read_register(dut, reg_sel=0) == 44

    # CLR then MAC
    await execute_opcode(dut, 0x4)  # Clear all
    await load_register(dut, 0, reg_sel=0)
    await load_register(dut, 100, reg_sel=1)
    await load_register(dut, 200, reg_sel=2)
    await execute_mac(dut)  # 0 + 100*200 = 20000
    assert await read_register(dut, reg_sel=0) == 20000

    # MAC then MUL
    await load_register(dut, 10, reg_sel=0)
    await load_register(dut, 2, reg_sel=1)
    await load_register(dut, 3, reg_sel=2)
    await execute_mac(dut)  # 10 + 2*3 = 16
    await load_register(dut, 4, reg_sel=1)
    await execute_mul(dut)  # 16 * 4 = 64
    assert await read_register(dut, reg_sel=0) == 64

    # MAC then ADD
    await load_register(dut, 50, reg_sel=0)
    await load_register(dut, 5, reg_sel=1)
    await load_register(dut, 10, reg_sel=2)
    await execute_mac(dut)  # 50 + 5*10 = 100
    await load_register(dut, 25, reg_sel=1)
    await execute_opcode(dut, 0x1)  # 100 + 25 = 125
    assert await read_register(dut, reg_sel=0) == 125

    dut._log.info("mac_after_other_ops: passed (6 operation sequences)")


@cocotb.test()
async def test_mac_power_of_two_folding(dut):
    """Test MAC with power-of-two values that trigger folding."""
    clock = Clock(dut.clk, 10, unit="us")
    cocotb.start_soon(clock.start())
    await reset_dut(dut)

    # 2^31 ≡ 1 (mod P), so products that equal 2^31 should fold to 1
    test_cases = [
        # Product folds: 2^30 * 2 = 2^31 ≡ 1
        (0, 0x40000000, 2, 1, "0 + 2^30*2 = 1"),
        (5, 0x40000000, 2, 6, "5 + 2^30*2 = 6"),
        (P-1, 0x40000000, 2, 0, "(P-1) + 1 = 0"),

        # 2^15 * 2^16 = 2^31 ≡ 1
        (0, 0x8000, 0x10000, 1, "0 + 2^15*2^16 = 1"),
        (100, 0x8000, 0x10000, 101, "100 + 1 = 101"),

        # 2^30 * 2^30 = 2^60 ≡ 2^29 (since 2^60 = 2^31 * 2^29 ≡ 1 * 2^29)
        (0, 0x40000000, 0x40000000, 0x20000000, "0 + 2^30*2^30 = 2^29"),
        (0x10000000, 0x40000000, 0x40000000, 0x30000000, "2^28 + 2^29 = 3*2^28"),

        # Chain of power-of-two MACs
        (0, 0x40000000, 4, 2, "0 + 2^30*4 = 2^32 = 2"),
        (0, 0x20000000, 8, 2, "0 + 2^29*8 = 2^32 = 2"),
        (0, 0x10000000, 16, 2, "0 + 2^28*16 = 2^32 = 2"),

        # Products just below and above 2^31
        (0, 0x3FFFFFFF, 2, 0x7FFFFFFE, "0 + (2^30-1)*2 = 2^31 - 2 = P-1"),
        (0, 0x40000001, 2, 3, "0 + (2^30+1)*2 = 2^31 + 2 = 3"),
    ]

    for reg_a, reg_b, reg_c, expected, desc in test_cases:
        await load_register(dut, reg_a, reg_sel=0)
        await load_register(dut, reg_b, reg_sel=1)
        await load_register(dut, reg_c, reg_sel=2)
        await execute_mac(dut)
        result = await read_register(dut, reg_sel=0)
        assert result == expected, f"MAC pow2 {desc}: expected {expected:#x}, got {result:#x}"

    dut._log.info("mac_power_of_two_folding: passed (12 test vectors)")
