/*
 * Copyright (c) 2025 Brendan Murrell
 * SPDX-License-Identifier: Apache-2.0
 *
 * M31-ACCEL: Mersenne-31 Arithmetic Accelerator
 * Hardware accelerator for modular arithmetic over the Mersenne-31 prime field
 * (p = 2^31 - 1) for ZK-STARK / Plonky3 applications.
 */
//
// Interface Protocol
// ==================
// All communication uses an 8-bit data bus (ui_in) and 4 control bits (uio_in).
//
//   Control bits: [0]=CMD_EN  [1]=REG_SEL[0]  [2]=RW  [3]=REG_SEL[1]
//   Register map: REG_SEL=00 -> A (accumulator)
//                 REG_SEL=01 -> B (operand)
//                 REG_SEL=10 -> C (MAC operand)
//
//   LOAD register: Set CMD_EN=0, RW=0, REG_SEL=target.
//                  Drive 4 bytes on ui_in (LSB-first), one per clock cycle.
//
//   EXECUTE op:    Set CMD_EN=1, drive opcode on ui_in[3:0], hold 1 cycle.
//                  For MUL/MAC, poll BUSY (uio_out[0]) until low before reading.
//
//   READ register: Set CMD_EN=0, RW=1, REG_SEL=target.
//                  Read 4 bytes from uo_out (LSB-first), one per clock cycle.
//                  Issue a NOP first to reset the read counter to byte 0.
//

`default_nettype none

module tt_um_brmurrell3_m31_accel (
    input  wire [7:0] ui_in,    // DATA[7:0] during load; OPCODE[3:0] during execute
    output wire [7:0] uo_out,   // RESULT byte during read
    input  wire [7:0] uio_in,   // [0]=CMD_EN, [1]=REG_SEL[0], [2]=RW, [3]=REG_SEL[1]
    output wire [7:0] uio_out,  // [0]=BUSY
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    // Control signals
    wire cmd_en = uio_in[0];
    wire rw     = uio_in[2];
    wire [1:0] reg_sel = {uio_in[3], uio_in[1]};  // Extended: 00=A, 01=B, 10=C

    // Registers
    reg [31:0] reg_a;
    reg [31:0] reg_b;
    reg [31:0] reg_c;      // Third register for MAC
    reg        mac_mode;   // Flag for MAC operation
    reg [1:0]  read_counter;
    reg [4:0]  mul_counter;
    reg [61:0] mul_accum;
    reg [30:0] mul_b_shift;
    reg [30:0] mul_operand_r;  // Captured operand - removes mux from critical path
    reg        reducing;       // Pipeline stage: reduction in progress

    // Mersenne-31 prime: p = 2^31 - 1
    localparam [31:0] P = 32'h7FFFFFFF;

    // Opcodes (OP_NOP handled by default case)
    /* verilator lint_off UNUSEDPARAM */
    localparam OP_NOP = 4'h0;
    /* verilator lint_on UNUSEDPARAM */
    localparam OP_ADD = 4'h1;
    localparam OP_SUB = 4'h2;
    localparam OP_MUL = 4'h3;
    localparam OP_CLR = 4'h4;
    localparam OP_MAC = 4'h5;

    wire [3:0] opcode = ui_in[3:0];

    // Bit-folding arithmetic intentionally mixes widths: 1-bit carries fold into
    // 31-bit fields, and 62-bit products reduce to 31 bits. Speculative subtraction
    // results are selected via the borrow (sign) bit. These width mismatches are
    // fundamental to Mersenne prime reduction and are correct by construction.
    // Formal verification (see `ifdef FORMAL block) proves all outputs stay in [0, P-1].
    /* verilator lint_off WIDTHEXPAND */
    /* verilator lint_off UNUSEDSIGNAL */

    // M31 Addition: (a + b) mod p using bit-folding since 2^31 ≡ 1 (mod p)
    // Inputs are in [0, P-1], so sum of 31-bit values is at most 2P-2.
    // After folding, result is at most P. Speculative subtraction: compute
    // both (fold) and (fold - P) in parallel, select via borrow bit.
    wire [31:0] add_raw = reg_a[30:0] + reg_b[30:0];
    wire [31:0] add_fold = add_raw[30:0] + add_raw[31];  // Intentional: fold carry bit
    wire [31:0] add_sub = add_fold - P;
    wire [31:0] add_result = add_sub[31] ? add_fold : add_sub[30:0];  // Intentional: 31-bit result

    // M31 Subtraction: (a - b) mod p
    // If result is negative (underflow), add P to wrap into [0, P-1].
    // Speculative subtraction: when both inputs equal P (the representation
    // of zero with bit 31 clear), sub_raw = 0 + P = P, which is not in
    // [0, P-1]. Speculatively subtract P and select via borrow, same as ADD.
    wire signed [31:0] sub_signed = $signed({1'b0, reg_a[30:0]}) - $signed({1'b0, reg_b[30:0]});
    wire [31:0] sub_raw  = sub_signed[31] ? (sub_signed + P) : sub_signed[30:0];
    wire [31:0] sub_spec = sub_raw - P;
    wire [31:0] sub_result = sub_spec[31] ? sub_raw : sub_spec[30:0];  // Intentional: 31-bit result

    // M31 Multiplication: shift-and-add, MSB-first
    // MUL: reg_a × reg_b, MAC: reg_b × reg_c
    // mul_operand_r is captured at multiply start to remove mux from critical path
    wire [61:0] mul_shifted = mul_accum << 1;
    wire [61:0] mul_next_accum = mul_b_shift[30] ? (mul_shifted + {31'b0, mul_operand_r}) : mul_shifted;

    // 62-bit to 31-bit reduction using double bit-folding
    // Product of two 31-bit values can be up to 62 bits. After two folds,
    // result can be up to P. Speculative subtraction selects via borrow bit.
    // Reads from mul_accum (registered) rather than mul_next_accum (combinational)
    // to pipeline the reduction — fires on the cycle after the inner loop completes.
    wire [31:0] mul_low = mul_accum[30:0];   // Intentional: extract lower 31 bits
    wire [31:0] mul_high = mul_accum[61:31]; // Intentional: extract upper 31 bits
    wire [32:0] mul_fold1 = mul_low + mul_high;   // mul_fold1[32] unused (folded via [31])
    wire [31:0] mul_fold2 = mul_fold1[30:0] + mul_fold1[31];  // Intentional: fold carry bit
    wire [31:0] mul_fold2_sub = mul_fold2 - P;
    wire [31:0] mul_result = mul_fold2_sub[31] ? mul_fold2 : mul_fold2_sub[30:0];  // Intentional: 31-bit result

    // MAC result: mul_result + reg_a (reg_a preserved during multiply)
    // Both mul_result and reg_a are in [0, P-1], so same folding as ADD applies.
    // Speculative subtraction selects via borrow bit.
    wire [31:0] mac_sum = mul_result[30:0] + reg_a[30:0];
    wire [31:0] mac_fold = mac_sum[30:0] + mac_sum[31];  // Intentional: fold carry bit
    wire [31:0] mac_sub = mac_fold - P;
    wire [31:0] mac_result = mac_sub[31] ? mac_fold : mac_sub[30:0];  // Intentional: 31-bit result

    /* verilator lint_on UNUSEDSIGNAL */
    /* verilator lint_on WIDTHEXPAND */

    // Outputs
    assign uio_oe = 8'b00000001;

    wire busy = (mul_counter != 5'b0) || reducing;
    assign uio_out = {7'b0, busy};

    // Optimized read_reg mux: binary tree structure for better synthesis
    wire [31:0] read_reg = reg_sel[1] ? reg_c : (reg_sel[0] ? reg_b : reg_a);

    // Optimized read_byte mux: direct bit-slice selection
    reg [7:0] read_byte;
    always @(*) begin
        case (read_counter)
            2'd0: read_byte = read_reg[7:0];
            2'd1: read_byte = read_reg[15:8];
            2'd2: read_byte = read_reg[23:16];
            2'd3: read_byte = read_reg[31:24];
        endcase
    end
    assign uo_out = read_byte;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_a        <= 32'b0;
            reg_b        <= 32'b0;
            reg_c        <= 32'b0;
            mac_mode     <= 1'b0;
            read_counter <= 2'b0;
            mul_counter  <= 5'b0;
            mul_accum    <= 62'b0;
            mul_b_shift  <= 31'b0;
            mul_operand_r <= 31'b0;
            reducing     <= 1'b0;
        end else begin
            // Register load (CMD_EN=0, RW=0, not busy)
            if (!cmd_en && !rw && !busy) begin
                case (reg_sel)
                    2'b00: reg_a <= {ui_in, reg_a[31:8]};
                    2'b01: reg_b <= {ui_in, reg_b[31:8]};
                    2'b10: reg_c <= {ui_in, reg_c[31:8]};
                    default: ;
                endcase
            end

            // Read counter
            if (!cmd_en && rw)
                read_counter <= read_counter + 2'd1;
            else
                read_counter <= 2'd0;

            // MAC mode tracking
            if (cmd_en && !busy) begin
                mac_mode <= (opcode == OP_MAC);
            end else if (!busy) begin
                mac_mode <= 1'b0;
            end

            // Multiplication state machine (shared by MUL and MAC)
            // Pipelined: inner loop (31 cycles) then reduction (1 cycle)
            if (mul_counter != 5'b0) begin
                // Inner loop: shift-and-add
                mul_accum <= mul_next_accum;
                mul_b_shift <= mul_b_shift << 1;
                mul_counter <= mul_counter - 5'd1;

                if (mul_counter == 5'd1)
                    reducing <= 1'b1;
            end else if (reducing) begin
                // Pipeline stage 2: reduce and write result
                reg_a <= mac_mode ? mac_result : mul_result;
                reducing <= 1'b0;
            end else if (cmd_en) begin
                case (opcode)
                    OP_ADD: reg_a <= add_result;
                    OP_SUB: reg_a <= sub_result;
                    OP_MUL: begin
                        mul_counter   <= 5'd31;
                        mul_accum     <= 62'b0;
                        mul_b_shift   <= reg_b[30:0];
                        mul_operand_r <= reg_a[30:0];  // Capture operand at start
                    end
                    OP_MAC: begin
                        mul_counter   <= 5'd31;
                        mul_accum     <= 62'b0;
                        mul_b_shift   <= reg_c[30:0];  // MAC uses reg_c
                        mul_operand_r <= reg_b[30:0];  // MAC multiplies reg_b
                    end
                    OP_CLR: begin
                        reg_a <= 32'b0;
                        reg_b <= 32'b0;
                        reg_c <= 32'b0;
                    end
                    default: ;
                endcase
            end
        end
    end

    wire _unused = &{ena, uio_in[7:4], 1'b0};

`ifdef FORMAL
    // ================================================================
    // Section 1: Setup
    // ================================================================
    reg f_past_valid;
    initial f_past_valid = 1'b0;
    always @(posedge clk) f_past_valid <= 1'b1;
    initial assume(!rst_n);

    // ================================================================
    // Section 2: Input contract
    // ================================================================
    //
    // Registers are loaded byte-serially over 4 clock cycles via the
    // 8-bit data bus.  Constraining individual byte writes to guarantee
    // field membership on the assembled 32-bit value would require
    // cross-cycle assumptions that are fragile and hard to audit.
    //
    // Instead, we assume the assembled register values are valid field
    // elements (< P).  This models the software contract: only valid
    // field elements are loaded.
    //
    // After the speculative-subtraction fix to SUB, the field-membership
    // assertions (Section 3) hold unconditionally — the assumes are NOT
    // required for *_result < P.  They ARE required for functional
    // correctness (Section 4), because the reference formulas assume
    // single-wrap arithmetic (sum < 2P, difference > -P).
    //
    always @(*) begin
        assume(reg_a < P);
        assume(reg_b < P);
        assume(reg_c < P);
    end

    // ================================================================
    // Section 3: Field membership — every arithmetic output is in [0, P-1]
    // ================================================================
    always @(posedge clk) if (rst_n) begin
        a_add_field: assert(add_result < P);
        a_sub_field: assert(sub_result < P);
        a_mul_field: assert(mul_result < P);
        a_mac_field: assert(mac_result < P);
    end

    // reg_a remains a valid field element after any operation writes to it
    always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n)) begin
        if ($past(cmd_en) && !$past(busy))
            a_reg_a_cmd: assert(reg_a < P);
        if ($past(reducing))
            a_reg_a_reduce: assert(reg_a < P);
    end

    // ================================================================
    // Section 4: Functional correctness — ADD and SUB match reference spec
    // ================================================================
    always @(posedge clk) if (rst_n) begin
        if ({1'b0, reg_a[30:0]} + {1'b0, reg_b[30:0]} >= P)
            a_add_hi: assert(add_result == ({1'b0, reg_a[30:0]} + {1'b0, reg_b[30:0]} - P));
        else
            a_add_lo: assert(add_result == ({1'b0, reg_a[30:0]} + {1'b0, reg_b[30:0]}));
    end

    always @(posedge clk) if (rst_n) begin
        if (reg_a[30:0] >= reg_b[30:0])
            a_sub_pos: assert(sub_result == (reg_a[30:0] - reg_b[30:0]));
        else
            a_sub_neg: assert(sub_result == (reg_a[30:0] - reg_b[30:0] + P));
    end

    // ================================================================
    // Section 5: Reset — all state clears on reset
    // ================================================================
    always @(posedge clk) if (f_past_valid && !$past(rst_n)) begin
        a_rst_reg_a:    assert(reg_a == 0);
        a_rst_reg_b:    assert(reg_b == 0);
        a_rst_reg_c:    assert(reg_c == 0);
        a_rst_counter:  assert(mul_counter == 0);
        a_rst_read_ctr: assert(read_counter == 0);
        a_rst_reducing: assert(reducing == 0);
    end

    // ================================================================
    // Section 6: Control logic
    // ================================================================
    // BUSY is the OR of active multiply and pending reduction
    always @(*) a_busy_def: assert(busy == (mul_counter != 0 || reducing));

    // Counter never exceeds 31
    always @(*) a_counter_max: assert(mul_counter <= 31);

    // Reduction takes exactly one cycle
    always @(*) if (reducing) a_reduce_one_cycle: assert(mul_counter == 0);
    always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n))
        a_reduce_no_stall: assert(!($past(reducing) && reducing));

    // Operands (reg_b, reg_c) are stable while multiply is in progress
    always @(posedge clk) if (f_past_valid && $past(rst_n) && rst_n && $past(busy) && busy) begin
        a_reg_b_stable: assert($stable(reg_b));
        a_reg_c_stable: assert($stable(reg_c));
    end

    // Counter decrements each active cycle
    always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n) && $past(mul_counter != 0))
        a_counter_dec: assert(mul_counter == $past(mul_counter) - 1);

    // ================================================================
    // Section 7: Reachability (cover)
    // ================================================================
    // Can complete a multiply and produce a non-zero result
    always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n))
        c_mul_nonzero: cover($past(reducing) && !reducing && reg_a != 0);

    // Can reach maximum field element P-1
    always @(posedge clk) if (f_past_valid && rst_n)
        c_max_element: cover(reg_a == (P - 1));

    // Can produce zero via addition (additive inverse)
    always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n))
        if ($past(cmd_en) && $past(opcode == OP_ADD) && !$past(busy))
            c_add_inverse: cover(reg_a == 0 && $past(reg_a) != 0);

    // Can complete a MAC operation
    always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n))
        c_mac_complete: cover($past(reducing) && !reducing && $past(mac_mode));
`endif

endmodule
