#pragma once
// Reading the dump folder: the files this project generates from your own copy of the game.
#include <cstdint>
#include <string>

namespace tld {

// One NSO0 module (main, sdk, rtld, subsdk*). Sizes come from the NSO header; the
// segments themselves are LZ4-compressed and are decompressed by the lifter, not here.
struct NsoInfo {
    std::string name;
    std::string path;
    uint64_t file_size = 0;
    uint64_t text_size = 0;
    uint64_t rodata_size = 0;
    uint64_t data_size = 0;
    uint64_t bss_size = 0;
    std::string build_id;  // hex, empty if the header did not look like NSO0
    bool ok = false;
};

struct Dump {
    std::string root;
    std::string exefs_dir;
    std::string romfs_dir;
    bool has_exefs = false;
    bool has_romfs = false;
    NsoInfo main_nso;
    NsoInfo sdk_nso;
    int npdm_size = 0;
};

// Reads <root>/exefs and <root>/romfs. Never modifies anything.
Dump load_dump(const std::string& root);

// Parses an NSO0 header. False if the file is missing or not an NSO0.
bool read_nso(const std::string& path, const std::string& name, NsoInfo& out);

// Human-readable report of what the dump contains.
std::string describe(const Dump& d);

}  // namespace tld
