/*
 * Copyright (c) 2024 Brendan Murrell
 * SPDX-License-Identifier: Apache-2.0
 *
 * M31-ACCEL: Mersenne-31 Arithmetic Accelerator
 * Hardware accelerator for modular arithmetic over the Mersenne-31 prime field
 * (p = 2^31 - 1) for ZK-STARK / Plonky3 applications.
 */

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

    // M31 Addition: (a + b) mod p using bit-folding since 2^31 ≡ 1 (mod p)
    // Inputs are in [0, P-1], so sum of 31-bit values is at most 2P-2.
    // After folding, result is at most P. Use == P check (not >=) because
    // the maximum folded value is exactly P when inputs sum to 2P-2.
    wire [31:0] add_raw = reg_a[30:0] + reg_b[30:0];
    /* verilator lint_off WIDTHEXPAND */
    wire [31:0] add_fold = add_raw[30:0] + add_raw[31];  // Intentional: fold carry bit
    /* verilator lint_on WIDTHEXPAND */
    wire [31:0] add_result = (add_fold == P) ? 32'b0 : add_fold;

    // M31 Subtraction: (a - b) mod p
    // If result is negative (underflow), add P to wrap into [0, P-1].
    wire signed [31:0] sub_signed = $signed({1'b0, reg_a[30:0]}) - $signed({1'b0, reg_b[30:0]});
    /* verilator lint_off WIDTHEXPAND */
    wire [31:0] sub_result = sub_signed[31] ? (sub_signed + P) : sub_signed[30:0];  // Intentional: 31-bit result
    /* verilator lint_on WIDTHEXPAND */

    // M31 Multiplication: shift-and-add, MSB-first
    // MUL: reg_a × reg_b, MAC: reg_b × reg_c
    // mul_operand_r is captured at multiply start to remove mux from critical path
    wire [61:0] mul_shifted = mul_accum << 1;
    wire [61:0] mul_next_accum = mul_b_shift[30] ? (mul_shifted + {31'b0, mul_operand_r}) : mul_shifted;

    // 62-bit to 31-bit reduction using double bit-folding
    // Product of two 31-bit values can be up to 62 bits. After two folds,
    // result can be up to P+1, so we use >= P check with subtraction.
    /* verilator lint_off WIDTHEXPAND */
    /* verilator lint_off UNUSEDSIGNAL */
    wire [31:0] mul_low = mul_next_accum[30:0];   // Intentional: extract lower 31 bits
    wire [31:0] mul_high = mul_next_accum[61:31]; // Intentional: extract upper 31 bits
    wire [32:0] mul_fold1 = mul_low + mul_high;   // mul_fold1[32] unused (folded via [31])
    wire [31:0] mul_fold2 = mul_fold1[30:0] + mul_fold1[31];  // Intentional: fold carry bit
    /* verilator lint_on UNUSEDSIGNAL */
    /* verilator lint_on WIDTHEXPAND */
    wire [31:0] mul_result = (mul_fold2 >= P) ? (mul_fold2 - P) : mul_fold2;

    // MAC result: mul_result + reg_a (reg_a preserved during multiply)
    // Both mul_result and reg_a are in [0, P-1], so same logic as ADD applies:
    // after folding, maximum value is exactly P, so == P check suffices.
    wire [31:0] mac_sum = mul_result[30:0] + reg_a[30:0];
    /* verilator lint_off WIDTHEXPAND */
    wire [31:0] mac_fold = mac_sum[30:0] + mac_sum[31];  // Intentional: fold carry bit
    /* verilator lint_on WIDTHEXPAND */
    wire [31:0] mac_result = (mac_fold == P) ? 32'b0 : mac_fold;

    // Outputs
    assign uio_oe = 8'b00000001;

    wire busy = (mul_counter != 5'b0);
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
            if (busy) begin
                mul_accum <= mul_next_accum;
                mul_b_shift <= mul_b_shift << 1;
                mul_counter <= mul_counter - 5'd1;

                if (mul_counter == 5'd1)
                    reg_a <= mac_mode ? mac_result : mul_result;
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
    reg f_past_valid;
    initial f_past_valid = 1'b0;
    always @(posedge clk) f_past_valid <= 1'b1;
    initial assume(!rst_n);

    // Assume valid field elements
    always @(*) begin
        assume(reg_a < P);
        assume(reg_b < P);
        assume(reg_c < P);
    end

    // Arithmetic outputs stay in field
    always @(posedge clk) if (rst_n) begin
        assert(add_result < P);
        assert(sub_result < P);
        assert(mul_result < P);
        assert(mac_result < P);
    end

    // Reset clears state
    always @(posedge clk) if (f_past_valid && !$past(rst_n)) begin
        assert(reg_a == 0);
        assert(reg_b == 0);
        assert(reg_c == 0);
        assert(mul_counter == 0);
    end

    // BUSY signal
    always @(*) assert(busy == (mul_counter != 0));
    always @(*) assert(mul_counter <= 31);

    // Operands stable during multiply
    always @(posedge clk) if (f_past_valid && $past(rst_n) && rst_n && $past(busy) && busy) begin
        assert($stable(reg_b));
        assert($stable(reg_c));
    end

    // Counter decrements each cycle
    always @(posedge clk) if (f_past_valid && rst_n && $past(rst_n) && $past(busy))
        assert(mul_counter == $past(mul_counter) - 1);
`endif

endmodule
