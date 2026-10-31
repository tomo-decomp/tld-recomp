// Guest CPU state and the memory model the lifted code runs against.
//
// The lifted C is mechanical: one C function per game function, registers in `Cpu::x`,
// control flow as goto/labels inside a function and plain C calls across functions. Nothing
// here interprets AArch64 at run time; these are the primitives the emitted code uses.
#pragma once
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>

namespace tld {

enum : uint32_t { FLAG_N = 8, FLAG_Z = 4, FLAG_C = 2, FLAG_V = 1 };

// Condition codes, as encoded in the instruction.
enum : int { COND_EQ = 0, COND_NE, COND_CS, COND_CC, COND_MI, COND_PL, COND_VS, COND_VC,
             COND_HI, COND_LS, COND_GE, COND_LT, COND_GT, COND_LE, COND_AL, COND_NV };

struct Cpu {
    uint64_t x[32];      // x0..x30, x31 reads as zero
    uint64_t sp;
    uint64_t pc;
    uint32_t nzcv;
    uint64_t tpidr_el0;  // thread pointer; the guest uses it for its TLS block
    uint64_t lr() const { return x[30]; }
    void set_lr(uint64_t v) { x[30] = v; }
};

// --- flags ------------------------------------------------------------------------------

static inline void set_nz(Cpu* c, uint64_t r, int width) {
    if (width == 32) r &= 0xFFFFFFFFu;
    uint64_t sign = (width == 32) ? (r >> 31) & 1 : (r >> 63) & 1;
    c->nzcv = (c->nzcv & ~(FLAG_N | FLAG_Z)) | (uint32_t)(sign ? FLAG_N : 0) | (r == 0 ? FLAG_Z : 0);
}

// add/sub with optional flag update; the operands' widths follow `width`.
static inline uint64_t alu_add(Cpu* c, uint64_t a, uint64_t b, int width, int setflags) {
    if (width == 32) {
        uint32_t r = (uint32_t)a + (uint32_t)b;
        if (setflags) {
            uint32_t s = (uint32_t)a, t = (uint32_t)b;
            c->nzcv = ((r >> 31) & 1 ? FLAG_N : 0) | (r == 0 ? FLAG_Z : 0)
                    | (r < s ? FLAG_C : 0) | (((s ^ r) & (t ^ r)) >> 31 ? FLAG_V : 0);
        }
        return r;
    }
    uint64_t r = a + b;
    if (setflags) {
        c->nzcv = ((r >> 63) & 1 ? FLAG_N : 0) | (r == 0 ? FLAG_Z : 0)
                | (r < a ? FLAG_C : 0) | (((~(a ^ b) & (a ^ r)) >> 63) ? FLAG_V : 0);
    }
    return r;
}

static inline uint64_t alu_sub(Cpu* c, uint64_t a, uint64_t b, int width, int setflags) {
    if (width == 32) {
        uint32_t r = (uint32_t)a - (uint32_t)b;
        if (setflags) {
            uint32_t s = (uint32_t)a, t = (uint32_t)b;
            c->nzcv = ((r >> 31) & 1 ? FLAG_N : 0) | (r == 0 ? FLAG_Z : 0)
                    | (s >= t ? FLAG_C : 0) | (((s ^ t) & (s ^ r)) >> 31 ? FLAG_V : 0);
        }
        return r;
    }
    uint64_t r = a - b;
    if (setflags) {
        c->nzcv = ((r >> 63) & 1 ? FLAG_N : 0) | (r == 0 ? FLAG_Z : 0)
                | (a >= b ? FLAG_C : 0) | (((a ^ b) & (a ^ r)) >> 63 ? FLAG_V : 0);
    }
    return r;
}

static inline uint64_t sext(uint64_t v, int bits) {
    uint64_t m = 1ull << (bits - 1);
    v &= (bits == 64) ? ~0ull : ((1ull << bits) - 1);
    return (v ^ m) - m;
}

static inline uint64_t ror64(uint64_t v, unsigned n) {
    n &= 63;
    return n ? (v >> n) | (v << (64 - n)) : v;
}

static inline int cond(const Cpu* c, int cc) {
    int n = (c->nzcv >> 3) & 1, z = (c->nzcv >> 2) & 1, cf = (c->nzcv >> 1) & 1, v = c->nzcv & 1;
    switch (cc) {
        case COND_EQ: return z;
        case COND_NE: return !z;
        case COND_CS: return cf;
        case COND_CC: return !cf;
        case COND_MI: return n;
        case COND_PL: return !n;
        case COND_VS: return v;
        case COND_VC: return !v;
        case COND_HI: return cf && !z;
        case COND_LS: return !cf || z;
        case COND_GE: return n == v;
        case COND_LT: return n != v;
        case COND_GT: return !z && n == v;
        case COND_LE: return z || n != v;
        default: return 1;
    }
}

// --- memory -----------------------------------------------------------------------------
//
// The guest sees a 39-bit address space. Pages are allocated on first touch, so a 6 GB data
// set costs what is actually read, not what is addressable. Unmapped access is reported and
// returns zero rather than trapping: a lift bug should not look like a hardware fault.

bool map(uint64_t addr, uint64_t size, int prot);
void* host_ptr(uint64_t addr, uint64_t size);   // nullptr when the range is not mapped

uint8_t  rd8(uint64_t a);
uint16_t rd16(uint64_t a);
uint32_t rd32(uint64_t a);
uint64_t rd64(uint64_t a);
void wr8(uint64_t a, uint64_t v);
void wr16(uint64_t a, uint64_t v);
void wr32(uint64_t a, uint64_t v);
void wr64(uint64_t a, uint64_t v);
int64_t  rds8(uint64_t a);
int64_t  rds16(uint64_t a);
int32_t  rds32(uint64_t a);

// Called by lifted code for instructions the lifter does not translate yet, and for calls
// whose target is outside .text (imports, which the HLE layer answers).
void unimpl(uint64_t pc, uint32_t insn);
void call_guest(Cpu* c, uint64_t target);       // generated dispatch table
void hle_svc(Cpu* c, uint32_t imm);             // svc #imm -> HLE service

}  // namespace tld
