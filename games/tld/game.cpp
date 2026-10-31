// Tomodachi Life: Living the Dream (010051F0207B2000): what the shared runtime needs to know about the game.
// Any version builds (games/tld/versions.txt); the addresses below would be the ones of 1.0.4. The hooks only run in a
// build recompiled with a hook list that has them, and what runs without a hook is applied only when main is a known
// build. The game draws through NVN; what we know about it is in docs/TOMODACHI.md.
#include <nx/game.h>
#include <nx/runtime.h>

namespace nx {

const game::Info game::kInfo = {"tld", "Tomodachi Life: Living the Dream", 0x010051F0207B2000ull,
                                "io.github.tldrecomp", "private/tld",
                                0 /* main.npdm: no system resource seen */,
                                0};

void game::after_init() {}
void game::renderer_start() {}
void game::first_frame() {}

}  // namespace nx
