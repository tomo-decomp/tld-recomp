#include "tld/dump.h"

#include <cstdio>
#include <filesystem>
#include <fstream>
#include <sstream>
#include <vector>

namespace fs = std::filesystem;

namespace tld {
namespace {

uint64_t size_of(const fs::path& p) {  // not file_size: that would collide with std::filesystem::file_size
    std::error_code ec;
    const auto n = fs::file_size(p, ec);
    return ec ? 0 : static_cast<uint64_t>(n);
}

std::string hex(const unsigned char* p, size_t n) {
    static const char* d = "0123456789abcdef";
    std::string s;
    s.reserve(n * 2);
    for (size_t i = 0; i < n; ++i) {
        s += d[p[i] >> 4];
        s += d[p[i] & 0xF];
    }
    return s;
}

uint32_t le32(const unsigned char* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) | (uint32_t(p[3]) << 24);
}

}  // namespace

bool read_nso(const std::string& path, const std::string& name, NsoInfo& out) {
    out = NsoInfo{};
    out.name = name;
    out.path = path;
    out.file_size = size_of(path);
    if (out.file_size == 0) return false;

    std::ifstream f(path, std::ios::binary);
    if (!f) return false;
    unsigned char h[0x100];
    f.read(reinterpret_cast<char*>(h), sizeof h);
    if (f.gcount() < static_cast<std::streamsize>(sizeof h)) return false;
    if (!(h[0] == 'N' && h[1] == 'S' && h[2] == 'O' && h[3] == '0')) return false;

    // Segments are (file offset, memory offset, decompressed size) triples at 0x10/0x20/0x30.
    out.text_size = le32(h + 0x10 + 0x08);
    out.rodata_size = le32(h + 0x20 + 0x08);
    out.data_size = le32(h + 0x30 + 0x08);
    out.bss_size = le32(h + 0x3C);
    out.build_id = hex(h + 0x40, 20);
    out.ok = true;
    return true;
}

Dump load_dump(const std::string& root) {
    Dump d;
    d.root = root;
    d.exefs_dir = (fs::path(root) / "exefs").string();
    d.romfs_dir = (fs::path(root) / "romfs").string();
    d.has_exefs = fs::is_directory(d.exefs_dir);
    d.has_romfs = fs::is_directory(d.romfs_dir);

    if (d.has_exefs) {
        const fs::path exefs(d.exefs_dir);
        read_nso((exefs / "main").string(), "main", d.main_nso);
        read_nso((exefs / "sdk").string(), "sdk", d.sdk_nso);
        d.npdm_size = static_cast<int>(size_of(exefs / "main.npdm"));
    }
    return d;
}

std::string describe(const Dump& d) {
    std::ostringstream o;
    o << "dump        " << d.root << '\n';
    o << "exefs       " << (d.has_exefs ? d.exefs_dir : std::string("(missing)")) << '\n';
    o << "romfs       " << (d.has_romfs ? d.romfs_dir : std::string("(missing)")) << '\n';
    if (d.main_nso.ok) {
        o << "main NSO    " << d.main_nso.file_size / (1024.0 * 1024.0) << " MB file, .text "
          << d.main_nso.text_size / (1024.0 * 1024.0) << " MB, .rodata " << d.main_nso.rodata_size / (1024.0 * 1024.0)
          << " MB, .data " << d.main_nso.data_size / (1024.0 * 1024.0) << " MB, .bss "
          << d.main_nso.bss_size / (1024.0 * 1024.0) << " MB\n";
        o << "main build  " << d.main_nso.build_id << '\n';
    } else {
        o << "main NSO    not found or not an NSO0\n";
    }
    if (d.sdk_nso.ok) {
        o << "sdk NSO     " << d.sdk_nso.file_size / (1024.0 * 1024.0) << " MB file, .text "
          << d.sdk_nso.text_size / (1024.0 * 1024.0) << " MB\n";
    }
    if (d.npdm_size) o << "main.npdm   " << d.npdm_size << " bytes\n";
    return o.str();
}

}  // namespace tld
