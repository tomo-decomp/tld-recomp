#pragma once
// Window, input and the graphics path. One implementation per host; this one covers
// Linux, Windows and macOS through SDL3, which is what the other ports in this
// repository use.
#include <string>

namespace tld {

struct Platform {
    bool video_ready = false;
    bool vulkan_ready = false;
    std::string video_driver;
    std::string vulkan_note;
};

// Probes the platform without opening a window (safe on a machine with no display).
Platform probe();

// Opens a window and runs the event loop for at most `frames` frames (0 = until the
// window is closed). Returns false if the window could not be created.
bool run_window(const std::string& title, int width, int height, int frames);

}  // namespace tld
