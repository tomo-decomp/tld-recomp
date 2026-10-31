cmake_minimum_required(VERSION 3.20)
project(tld_recomp LANGUAGES C CXX)

# Tomodachi Life: Living the Dream, native recompilation.
#
# The runtime in runtime/ is the shared nx:: one (NVN -> Vulkan, HLE services, kernel, saves, UI);
# the game's own compiled code is generated from your dump by tools/recomp and linked in from
# NX_GEN_DIR (tools/setup_tld.py writes it). This file builds both, like ACNHRecomp's CMakeLists.
#
#   cmake -S . -B build -DNX_GAME=tld -DNX_GEN_DIR=private/tld/gen
#   cmake --build build
#
# Without NX_GEN_DIR the runtime still builds (and reports that it has no game modules).

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)
if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

set(NX_GAME "tld" CACHE STRING "Game folder under games/ (its game.cpp, its identity)")
set(NX_GEN_DIR "" CACHE PATH "Generated game modules from tools/recomp (<dir>/main, <dir>/sdk, ...)")
set(NX_MODULES "main;sdk" CACHE STRING "Modules in NX_GEN_DIR to link (ACNH-style: sdk, subsdk0, main)")
set(NX_GAME_ABI "tld-1" CACHE STRING "The generated-code ABI the player and the game library agree on")
set(NX_VERSION_STRING "dev" CACHE STRING "Version shown by the player")
set(NX_VULKAN_INCLUDE "" CACHE PATH "Vulkan headers, when not found by find_package")
option(NX_LAUNCHER "Build the first-run launcher (needs SDL3 and Dear ImGui)" OFF)
option(NX_TESTS "Build the standalone unit tests (ctest)" OFF)
set(NX_GAME_OPT "" CACHE STRING "Optimization for the generated game module(s) only, e.g. -O1; empty keeps the build type's")
option(NX_GAME_DYNAMIC "Load the game modules from the data folder at run time instead of linking them" OFF)

find_package(Threads REQUIRED)
find_package(SDL3 REQUIRED)
find_package(Vulkan QUIET)
if(NOT Vulkan_FOUND AND NX_VULKAN_INCLUDE)
  set(Vulkan_INCLUDE_DIRS "${NX_VULKAN_INCLUDE}")
endif()

# ---- the game's recompiled code: one library, one table per module (nx_module_<name>) ---------------------------
set(NX_GEN_MODULES)
set(NX_GEN_INCLUDES)
if(NX_GEN_DIR)
  foreach(mod ${NX_MODULES})
    if(EXISTS "${NX_GEN_DIR}/${mod}/table.cpp")
      list(APPEND NX_GEN_MODULES ${mod})
      file(GLOB NX_GEN_${mod}_SRC "${NX_GEN_DIR}/${mod}/code_*.cpp")
      list(APPEND NX_GAME_SOURCES ${NX_GEN_${mod}_SRC} "${NX_GEN_DIR}/${mod}/table.cpp")
      list(APPEND NX_GEN_INCLUDES "${NX_GEN_DIR}/${mod}")
      list(LENGTH NX_GEN_${mod}_SRC n)
      message(STATUS "tld: module ${mod}: ${n} translation unit(s)")
    else()
      message(WARNING "tld: module ${mod} has no table.cpp in ${NX_GEN_DIR}; not linked")
    endif()
  endforeach()
endif()

# ---- the runtime ----------------------------------------------------------------------------------------------
file(GLOB NX_RUNTIME_SRC "${CMAKE_SOURCE_DIR}/runtime/src/*.cpp")
list(FILTER NX_RUNTIME_SRC EXCLUDE REGEX "/platform_(win|mac|android|android_audio|android_input)\\.cpp$")
# platform_sdl.cpp is the SDL3 half that platform_win.cpp completes; the Linux and macOS hosts already carry their
# own window, audio and main (platform_linux.cpp, platform_mac.cpp), so compiling it there too duplicates
# nx::plat::headless(), g_volume, g_refresh_hz and the rest. It is added back for Windows below.
list(FILTER NX_RUNTIME_SRC EXCLUDE REGEX "/platform_sdl\\.cpp$")
list(FILTER NX_RUNTIME_SRC EXCLUDE REGEX "/memguard_(win|mac|android)\\.cpp$")
list(FILTER NX_RUNTIME_SRC EXCLUDE REGEX "/dump\\.cpp$")     # the old tld:: runtime, replaced by the nx:: one
list(FILTER NX_RUNTIME_SRC EXCLUDE REGEX "/guest\\.cpp$")
list(FILTER NX_RUNTIME_SRC EXCLUDE REGEX "/hle\\.cpp$")

# The renderer (nvn/), the settings screen (ui/) and the Metal shader pair (mtl/) live in subdirectories: the glob
# above only sees runtime/src itself, so without these the link fails on nx::nvn::guest_call, nx::ui::ui_event, ...
file(GLOB NX_NVN_SRC "${CMAKE_SOURCE_DIR}/runtime/src/nvn/*.cpp")
list(APPEND NX_RUNTIME_SRC ${NX_NVN_SRC} runtime/src/ui/i18n.cpp)
# ui.cpp and settings.cpp draw the screen with Dear ImGui, which this tree does not vendor; ui_stub.cpp defines the
# same nx::ui:: entry points as no-ops (config.ini still applies), which is what the runtime ships it for.
if(EXISTS "${CMAKE_SOURCE_DIR}/third_party/imgui")
  list(APPEND NX_RUNTIME_SRC runtime/src/ui/ui.cpp runtime/src/ui/settings.cpp runtime/src/ui/theme.cpp)
else()
  list(APPEND NX_RUNTIME_SRC runtime/src/ui/ui_stub.cpp)
  message(STATUS "tld: no third_party/imgui; settings screen stubbed (ui_stub.cpp)")
endif()
if(APPLE)
  file(GLOB NX_MTL_SRC "${CMAKE_SOURCE_DIR}/runtime/src/mtl/*.cpp")
  list(APPEND NX_RUNTIME_SRC ${NX_MTL_SRC})
endif()

if(WIN32)
  list(APPEND NX_RUNTIME_SRC runtime/src/platform_win.cpp runtime/src/platform_sdl.cpp
       runtime/src/memguard_win.cpp)
elseif(APPLE)
  list(APPEND NX_RUNTIME_SRC runtime/src/platform_mac.cpp runtime/src/memguard_mac.cpp)
else()
  list(APPEND NX_RUNTIME_SRC runtime/src/platform_linux.cpp runtime/src/memguard_linux.cpp)
endif()
list(APPEND NX_RUNTIME_SRC games/${NX_GAME}/game.cpp)

add_executable(${NX_GAME} ${NX_RUNTIME_SRC})
target_include_directories(${NX_GAME} PRIVATE runtime/include runtime/src runtime/src/nvn runtime/src/ui
                                     ${NX_GEN_INCLUDES})
target_link_libraries(${NX_GAME} PRIVATE SDL3::SDL3 Threads::Threads)
if(Vulkan_FOUND)
  target_link_libraries(${NX_GAME} PRIVATE Vulkan::Vulkan)
elseif(Vulkan_INCLUDE_DIRS)
  target_include_directories(${NX_GAME} PRIVATE ${Vulkan_INCLUDE_DIRS})
endif()
if(UNIX AND NOT APPLE)
  target_link_libraries(${NX_GAME} PRIVATE dl)
endif()

# hle_movie.cpp decodes VP8/VP9 and Vorbis on the CPU with libvpx and libvorbis; without libvpx it still builds
# (NX_NO_VPX means video frames come out black, as its header says).
find_package(PkgConfig QUIET)
if(PkgConfig_FOUND)
  pkg_check_modules(NX_VPX QUIET vpx)
  pkg_check_modules(NX_VORBIS QUIET vorbis)
endif()
if(NX_VPX_FOUND)
  target_link_libraries(${NX_GAME} PRIVATE ${NX_VPX_LIBRARIES})
  target_include_directories(${NX_GAME} PRIVATE ${NX_VPX_INCLUDE_DIRS})
else()
  target_compile_definitions(${NX_GAME} PRIVATE NX_NO_VPX=1)
  message(STATUS "tld: libvpx not found; movie video will be black")
endif()
if(NX_VORBIS_FOUND)
  target_link_libraries(${NX_GAME} PRIVATE ${NX_VORBIS_LIBRARIES})
  target_include_directories(${NX_GAME} PRIVATE ${NX_VORBIS_INCLUDE_DIRS})
endif()

target_compile_definitions(${NX_GAME} PRIVATE
  NX_GAME="${NX_GAME}"
  NX_GAME_ABI="${NX_GAME_ABI}"
  NX_VERSION_STRING="${NX_VERSION_STRING}"
  NX_HAS_MAIN=1)
foreach(mod ${NX_GEN_MODULES})
  if(NOT mod STREQUAL "main")
    string(TOUPPER "${mod}" mod_upper)
    target_compile_definitions(${NX_GAME} PRIVATE NX_HAS_${mod_upper}=1)
  endif()
endforeach()
if(NX_GAME_DYNAMIC)
  target_compile_definitions(${NX_GAME} PRIVATE NX_GAME_DYNAMIC=1)
endif()

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(${NX_GAME} PRIVATE -Wall -Wextra -Wno-unused-parameter -Wno-missing-field-initializers)
endif()

# The generated code is mechanical: its warnings are the lifter's, not yours.
if(NX_GAME_SOURCES)
  add_library(${NX_GAME}_game STATIC ${NX_GAME_SOURCES})
  target_include_directories(${NX_GAME}_game PUBLIC runtime/include ${NX_GEN_INCLUDES})
  target_compile_options(${NX_GAME}_game PRIVATE -w)
  if(NX_GAME_OPT)
    # Appended after the build type's -O: -O0/-O1 links the same code several times faster than -O3, and
    # -fno-stack-protector matters most here (the canary scan is superlinear in the size of these functions).
    separate_arguments(NX_GAME_OPT_LIST UNIX_COMMAND "${NX_GAME_OPT}")
    target_compile_options(${NX_GAME}_game PRIVATE ${NX_GAME_OPT_LIST})
  endif()
  target_link_libraries(${NX_GAME} PRIVATE ${NX_GAME}_game)
  foreach(mod ${NX_GEN_MODULES})
    if(NOT mod STREQUAL "main")
      string(TOUPPER "${mod}" mod_upper)
      target_compile_definitions(${NX_GAME}_game PUBLIC NX_HAS_${mod_upper}=1)
    endif()
  endforeach()
endif()

if(NX_TESTS)
  # Unit tests of runtime pieces that build without the game: ctest, as ACNHRecomp does.
  enable_testing()
  add_executable(gpu_pick_test tests/gpu_pick_test.cpp runtime/src/nvn/nvn_gpu_pick.cpp)
  target_compile_definitions(gpu_pick_test PRIVATE NX_GPU_PICK_STANDALONE)
  target_include_directories(gpu_pick_test PRIVATE runtime/src/nvn)
  add_test(NAME gpu_pick COMMAND gpu_pick_test)
  add_executable(tiling_test tests/tiling_test.cpp runtime/src/nvn/nvn_tiling.cpp)
  target_include_directories(tiling_test PRIVATE runtime/src/nvn)
  add_test(NAME tiling COMMAND tiling_test --selftest)
  add_executable(astc_test tests/astc_test.cpp runtime/src/nvn/nvn_astc.cpp)
  target_include_directories(astc_test PRIVATE runtime/src/nvn)
  add_test(NAME astc COMMAND astc_test --selftest)
  add_executable(shader_cache_test tests/shader_cache_test.cpp runtime/src/nvn/nvn_shaders.cpp
                 runtime/src/nvn/nvn_spirv_reflect.cpp)
  target_compile_definitions(shader_cache_test PRIVATE NX_SHADERS_STANDALONE)
  target_include_directories(shader_cache_test PRIVATE runtime/src/nvn)
  if(EXISTS "${CMAKE_SOURCE_DIR}/private/tld")
    add_test(NAME shader_cache COMMAND shader_cache_test "${CMAKE_SOURCE_DIR}/private/tld")
  endif()
  if(WIN32)
    add_executable(memguard_test tests/memguard_test.cpp)
    target_link_libraries(memguard_test PRIVATE psapi)
    add_test(NAME memguard COMMAND memguard_test)
  endif()
endif()

if(NX_LAUNCHER)
  include(launcher/launcher.cmake)
endif()

install(TARGETS ${NX_GAME} RUNTIME DESTINATION bin)
