#include "tld/guest.h"

namespace tld {
namespace {

constexpr int PAGE_BITS = 12;
constexpr uint64_t PAGE_SIZE_ = 1ull << PAGE_BITS;
constexpr uint64_t PAGES = 1ull << 27;            // 512 GB of addressable space, sparse
uint8_t** page_table = nullptr;                   // lazily allocated directory of pages

inline uint8_t* page_of(uint64_t a, bool make) {
    if (!page_table) {
        if (!make) return nullptr;
        page_table = static_cast<uint8_t**>(std::calloc(PAGES, sizeof(uint8_t*)));
        if (!page_table) std::abort();
    }
    uint64_t i = a >> PAGE_BITS;
    if (i >= PAGES) return nullptr;
    uint8_t*& p = page_table[i];
    if (!p && make) {
        p = static_cast<uint8_t*>(std::calloc(1, PAGE_SIZE_));
        if (!p) std::abort();
    }
    return p;
}

// A page table of pointers keeps this simple, but callers in tight loops want one entry
// lookup rather than two; the fast path covers the common case of a fully mapped 8-byte read.
inline uint8_t* need(uint64_t a) {
    uint8_t* p = page_of(a, true);
    if (!p) std::abort();
    return p;
}

void fault(uint64_t a, const char* what) {
    static int reported = 0;
    if (reported++ < 32)
        std::fprintf(stderr, "tld: %s of unmapped guest address %016llx\n", what,
                     static_cast<unsigned long long>(a));
}

}  // namespace

bool map(uint64_t addr, uint64_t size, int) {
    if (!size) size = 1;
    uint64_t first = addr >> PAGE_BITS, last = (addr + size - 1) >> PAGE_BITS;
    for (uint64_t i = first; i <= last; ++i) page_of(i << PAGE_BITS, true);
    return true;
}

void* host_ptr(uint64_t addr, uint64_t size) {
    uint8_t* p = page_of(addr, false);
    if (!p) return nullptr;
    uint64_t off = addr & (PAGE_SIZE_ - 1);
    if (off + size > PAGE_SIZE_) return nullptr;   // a range that straddles a page: slow path
    return p + off;
}

uint8_t rd8(uint64_t a) { return *reinterpret_cast<uint8_t*>(need(a) + (a & (PAGE_SIZE_ - 1))); }
uint16_t rd16(uint64_t a) { uint16_t v; std::memcpy(&v, need(a) + (a & (PAGE_SIZE_ - 1)), 2); return v; }
uint32_t rd32(uint64_t a) { uint32_t v; std::memcpy(&v, need(a) + (a & (PAGE_SIZE_ - 1)), 4); return v; }
uint64_t rd64(uint64_t a) { uint64_t v; std::memcpy(&v, need(a) + (a & (PAGE_SIZE_ - 1)), 8); return v; }

void wr8(uint64_t a, uint64_t v) { *reinterpret_cast<uint8_t*>(need(a) + (a & (PAGE_SIZE_ - 1))) = (uint8_t)v; }
void wr16(uint64_t a, uint64_t v) { uint16_t t = (uint16_t)v; std::memcpy(need(a) + (a & (PAGE_SIZE_ - 1)), &t, 2); }
void wr32(uint64_t a, uint64_t v) { uint32_t t = (uint32_t)v; std::memcpy(need(a) + (a & (PAGE_SIZE_ - 1)), &t, 4); }
void wr64(uint64_t a, uint64_t v) { std::memcpy(need(a) + (a & (PAGE_SIZE_ - 1)), &v, 8); }

int64_t rds8(uint64_t a) { return (int8_t)rd8(a); }
int64_t rds16(uint64_t a) { return (int16_t)rd16(a); }
int32_t rds32(uint64_t a) { return (int32_t)rd32(a); }

void unimpl(uint64_t pc, uint32_t insn) {
    static int reported = 0;
    if (reported++ < 64)
        std::fprintf(stderr, "tld: unlifted instruction %08x at %016llx\n", insn,
                     static_cast<unsigned long long>(pc));
}

// SVC from game code is the supervisor call into what the console's kernel provided. The
// HLE layer is reached through the service dispatcher, not through the vector table, so this
// records the call site and returns: the same request will next arrive as a named service
// request, which is where it can actually be answered.
void hle_svc(Cpu* c, uint32_t imm) {
    static int reported = 0;
    if (reported++ < 16)
        std::fprintf(stderr, "tld: svc #%u at %016llx (pc set by lifted code)\n", imm,
                     static_cast<unsigned long long>(c->pc));
}

}  // namespace tld
