#pragma once
// What the console provided, re-implemented on the host: the service dispatcher.
//
// Recompiled game code reaches the system through HIPC requests (service name + command
// id + arguments). The lifter emits one call per request into this registry, so the
// behaviour of a system service can be written once, in C++, and replaced piecemeal.
#include <cstdint>
#include <functional>
#include <string>
#include <unordered_map>
#include <vector>

namespace tld {

struct Request {
    const char* service = nullptr;
    uint32_t command = 0;
    const uint64_t* args = nullptr;
    size_t arg_count = 0;
};

struct Reply {
    uint64_t value = 0;
    bool ok = true;
};

using Handler = std::function<Reply(const Request&)>;

class Hle {
public:
    void register_service(const std::string& service, uint32_t command, Handler h);

    // Called by recompiled code. Returns 0 and sets ok=false for an unimplemented request,
    // so a missing service shows up as a named failure instead of a wrong result.
    Reply invoke(const char* service, uint32_t command, const uint64_t* args, size_t arg_count);

    size_t handler_count() const { return handlers_.size(); }
    size_t request_count() const { return requests_; }
    std::vector<std::string> services() const;
    std::vector<std::string> missing() const;

private:
    static uint64_t key(const std::string& service, uint32_t command);
    std::unordered_map<uint64_t, Handler> handlers_;
    std::unordered_map<uint64_t, std::string> names_;
    std::vector<std::string> missing_;
    size_t requests_ = 0;
};

// The process-wide registry the generated code links against.
Hle& hle();

// Registers the small set of services the runtime can answer today (time, and the
// safe-to-stub ones). Everything else reports as missing.
void register_builtin_services();

}  // namespace tld
