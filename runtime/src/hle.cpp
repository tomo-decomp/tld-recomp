#include "tld/hle.h"

#include <algorithm>
#include <chrono>

namespace tld {
namespace {
std::string key_name(const std::string& service, uint32_t command) {
    char buf[16];
    std::snprintf(buf, sizeof buf, "%u", command);
    return service + "#" + buf;
}
}  // namespace

uint64_t Hle::key(const std::string& service, uint32_t command) {
    // 64-bit mix of the service name and the command id; collisions are impossible in
    // practice for the few hundred requests a game uses, and are detected on insert.
    uint64_t h = 1469598103934665603ull;
    for (unsigned char c : service) {
        h ^= c;
        h *= 1099511628211ull;
    }
    h ^= (uint64_t(command) << 1);
    h *= 1099511628211ull;
    return h;
}

void Hle::register_service(const std::string& service, uint32_t command, Handler h) {
    handlers_[key(service, command)] = std::move(h);
    names_[key(service, command)] = key_name(service, command);
}

Reply Hle::invoke(const char* service, uint32_t command, const uint64_t* args, size_t arg_count) {
    ++requests_;
    if (!service) return Reply{0, false};
    const uint64_t k = key(service, command);
    const auto it = handlers_.find(k);
    if (it == handlers_.end()) {
        const std::string name = key_name(service, command);
        if (std::find(missing_.begin(), missing_.end(), name) == missing_.end()) missing_.push_back(name);
        return Reply{0, false};
    }
    Request r{service, command, args, arg_count};
    return it->second(r);
}

std::vector<std::string> Hle::services() const {
    std::vector<std::string> out;
    out.reserve(names_.size());
    for (const auto& kv : names_) out.push_back(kv.second);
    std::sort(out.begin(), out.end());
    return out;
}

std::vector<std::string> Hle::missing() const { return missing_; }

Hle& hle() {
    static Hle instance;
    return instance;
}

void register_builtin_services() {
    // nn::time::StandardUserSystemClock::GetCurrentTime
    hle().register_service("time:u", 0, [](const Request&) {
        const auto now = std::chrono::system_clock::now().time_since_epoch();
        return Reply{static_cast<uint64_t>(
                         std::chrono::duration_cast<std::chrono::nanoseconds>(now).count()) +
                         11644473600000000000ull,  // 1970 -> 1601 (Switch epoch)
                     true};
    });
    // nn::os::GetCurrentThreadId / process id style identity calls answer a constant.
    hle().register_service("set:sys", 0, [](const Request&) { return Reply{0, true}; });
}

}  // namespace tld
