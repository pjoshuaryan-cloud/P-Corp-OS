/*
 * The thin native shim TECH_STACK.md's packaging plan calls for. Its job:
 * resolve the bundle-relative embedded Python interpreter, set PYTHONHOME,
 * and exec the backend entrypoint. This is what SMAppService actually
 * registers as the LaunchAgent target (stage 3) — not the Python process
 * directly, and not the SwiftUI app.
 *
 * C, not Swift, per TECH_STACK.md's own "Swift/C shim" framing — zero
 * runtime dependencies for a background helper that should be as simple
 * and reliable as possible.
 *
 * PYTHONHOME points at the embedded runtime inside the bundle (relocatable,
 * confirmed directly: extracted, moved to a different path, still ran
 * correctly) — that's the actual point of stage 2, decoupling from this
 * dev machine's own `uv`-managed venv and system Python. PYTHONPATH
 * deliberately still points at the real repo's backend/ directory, NOT a
 * copy embedded in the bundle: db.py's data path is relative to its own
 * file location, so a bundled copy would silently fork Frank's memory into
 * a second SQLite database depending on which way he's launched — breaking
 * "there is only ever one Frank." Fully self-contained source (for actual
 * distribution to a machine that doesn't have this repo) is a real, later
 * decision, not assumed here — this project is still single-machine and
 * git-versioned, not distributed anywhere yet.
 *
 * Compiled by desktop/build_app.sh via `clang`, not part of the SwiftPM
 * target — it's a separate executable at Contents/MacOS/PCorpOSBackend,
 * alongside the SwiftUI app's own Contents/MacOS/PCorpOS.
 */
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <libgen.h>
#include <mach-o/dyld.h>
#include <unistd.h>

#ifndef PCORPOS_BACKEND_SOURCE_PATH
#error "PCORPOS_BACKEND_SOURCE_PATH must be defined at compile time (see build_app.sh)"
#endif

int main(int argc, char *argv[]) {
    char exec_path[4096];
    uint32_t size = sizeof(exec_path);
    if (_NSGetExecutablePath(exec_path, &size) != 0) {
        fprintf(stderr, "PCorpOSBackend: executable path too long\n");
        return 1;
    }

    /* dirname() may return a pointer into a static/shared buffer depending
     * on the libc implementation — copy the input before each call rather
     * than chaining dirname(dirname(...)) directly. */
    char path_copy[4096];
    strncpy(path_copy, exec_path, sizeof(path_copy) - 1);
    path_copy[sizeof(path_copy) - 1] = '\0';
    char *macos_dir = dirname(path_copy); /* .../Contents/MacOS */

    char macos_dir_copy[4096];
    strncpy(macos_dir_copy, macos_dir, sizeof(macos_dir_copy) - 1);
    macos_dir_copy[sizeof(macos_dir_copy) - 1] = '\0';
    char *contents_dir = dirname(macos_dir_copy); /* .../Contents */

    char python_home[4096];
    snprintf(python_home, sizeof(python_home), "%s/Resources/python", contents_dir);

    char python_bin[4096];
    snprintf(python_bin, sizeof(python_bin), "%s/bin/python3.12", python_home);

    setenv("PYTHONHOME", python_home, 1);
    setenv("PYTHONPATH", PCORPOS_BACKEND_SOURCE_PATH, 1);

    execl(python_bin, python_bin, "-c", "from app.main import run; run()", (char *)NULL);

    /* execl only returns on failure */
    fprintf(stderr, "PCorpOSBackend: failed to exec %s: %s\n", python_bin, strerror(errno));
    return 1;
}
