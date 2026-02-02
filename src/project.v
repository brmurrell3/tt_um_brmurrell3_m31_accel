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
    input  wire [7:0] uio_in,   // [0]=CMD_EN, [1]=REG_SEL, [2]=RW
    output wire [7:0] uio_out,  // [0]=BUSY
    output wire [7:0] uio_oe,
    input  wire       ena,
    input  wire       clk,
    input  wire       rst_n
);

    // Control signals
    wire cmd_en  = uio_in[0];
    wire reg_sel = uio_in[1];
    wire rw      = uio_in[2];

    // Registers
    reg [31:0] reg_a;
    reg [31:0] reg_b;
    reg [1:0]  read_counter;
    reg [4:0]  mul_counter;
    reg [61:0] mul_accum;
    reg [30:0] mul_b_shift;

    // Opcodes
    localparam OP_NOP = 4'h0;
    localparam OP_ADD = 4'h1;
    localparam OP_SUB = 4'h2;
    localparam OP_MUL = 4'h3;
    localparam OP_CLR = 4'h4;

    wire [3:0] opcode = ui_in[3:0];

    // M31 Addition: (a + b) mod p using bit-folding since 2^31 = 1 (mod p)
    wire [31:0] add_raw = reg_a[30:0] + reg_b[30:0];
    wire [31:0] add_fold = add_raw[30:0] + add_raw[31];
    wire [31:0] add_result = (add_fold == 32'h7FFFFFFF) ? 32'b0 : add_fold;

    // M31 Subtraction: (a - b) mod p
    wire signed [31:0] sub_signed = $signed({1'b0, reg_a[30:0]}) - $signed({1'b0, reg_b[30:0]});
    wire [31:0] sub_result = sub_signed[31] ? (sub_signed + 32'h7FFFFFFF) : sub_signed[30:0];

    // M31 Multiplication: shift-and-add, MSB-first
    wire [61:0] mul_shifted = mul_accum << 1;
    wire [61:0] mul_next_accum = mul_b_shift[30] ? (mul_shifted + {31'b0, reg_a[30:0]}) : mul_shifted;

    // 62-bit to 31-bit reduction
    wire [31:0] mul_low = mul_next_accum[30:0];
    wire [31:0] mul_high = mul_next_accum[61:31];
    wire [32:0] mul_fold1 = mul_low + mul_high;
    wire [31:0] mul_fold2 = mul_fold1[30:0] + mul_fold1[31];
    wire [31:0] mul_result = (mul_fold2 >= 32'h7FFFFFFF) ? (mul_fold2 - 32'h7FFFFFFF) : mul_fold2;

    // Outputs
    assign uio_oe = 8'b00000001;

    wire busy = (mul_counter != 5'b0);
    assign uio_out = {7'b0, busy};

    wire [31:0] read_reg = reg_sel ? reg_b : reg_a;
    wire [7:0] read_byte = (read_counter == 2'd0) ? read_reg[7:0]   :
                           (read_counter == 2'd1) ? read_reg[15:8]  :
                           (read_counter == 2'd2) ? read_reg[23:16] :
                                                    read_reg[31:24];
    assign uo_out = read_byte;

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            reg_a        <= 32'b0;
            reg_b        <= 32'b0;
            read_counter <= 2'b0;
            mul_counter  <= 5'b0;
            mul_accum    <= 62'b0;
            mul_b_shift  <= 31'b0;
        end else begin
            // Register load (CMD_EN=0, RW=0, not busy)
            if (!cmd_en && !rw && !busy) begin
                if (!reg_sel)
                    reg_a <= {ui_in, reg_a[31:8]};
                else
                    reg_b <= {ui_in, reg_b[31:8]};
            end

            // Read counter
            if (!cmd_en && rw)
                read_counter <= read_counter + 2'd1;
            else
                read_counter <= 2'd0;

            // Multiplication state machine
            if (busy) begin
                mul_accum <= mul_next_accum;
                mul_b_shift <= mul_b_shift << 1;
                mul_counter <= mul_counter - 5'd1;

                if (mul_counter == 5'd1)
                    reg_a <= mul_result;
            end else if (cmd_en) begin
                case (opcode)
                    OP_ADD: reg_a <= add_result;
                    OP_SUB: reg_a <= sub_result;
                    OP_MUL: begin
                        mul_counter <= 5'd31;
                        mul_accum   <= 62'b0;
                        mul_b_shift <= reg_b[30:0];
                    end
                    OP_CLR: begin
                        reg_a <= 32'b0;
                        reg_b <= 32'b0;
                    end
                    default: ;
                endcase
            end
        end
    end

    wire _unused = &{ena, uio_in[7:3], 1'b0};

endmodule
