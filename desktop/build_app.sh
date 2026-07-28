#!/bin/bash
# SMAppService packaging (TECH_STACK.md), stages 1 + 2.
#
# Stage 1: turns the raw SPM executable into a real .app bundle. This
# project has run via `swift build`/`swift run` from day one (no Xcode
# installed, only command-line tools) — that's the same root cause behind
# the activation-policy/Dock-icon workarounds already in ContentView.swift,
# and the EventKit/UNUserNotificationCenter failures worked around with
# AppleScript. A real bundle doesn't remove those workarounds (not touched
# here, on purpose — a separate, deliberate cleanup once this is proven
# stable), but it's the actual prerequisite SMAppService needs to register
# a persistent LaunchAgent at all.
#
# Stage 2: embeds a self-contained, relocatable Python runtime (python-
# build-standalone) + the exact locked dependencies (via `uv export`) as a
# bundled resource, plus a thin native C shim (backend_shim.c) that resolves
# the embedded interpreter and execs the backend — decoupling from this
# dev machine's own `uv`-managed venv and system Python. The shim's
# PYTHONPATH deliberately still points at the real repo's backend/ source,
# not a bundled copy — see backend_shim.c's own comment for why (forking
# Frank's SQLite data directory depending on launch method would be worse
# than the coupling this avoids).
#
# Stage 3: writes the Contents/Library/LaunchAgents/<label>.plist
# SMAppService.agent(plistName:) requires to register the shim as a real
# persistent background service (BackendService.swift, wired to the
# Settings "Launch at Login" toggle) — the step that actually delivers an
# always-running Frank, not just a bundled backend still launched by hand.
#
# Re-run this after every code change instead of `swift build` when you want
# to test the bundled form specifically. `swift run` during normal
# development is unaffected and still works exactly as before.
set -euo pipefail

cd "$(dirname "$0")"
REPO_ROOT="$(cd .. && pwd)"

APP_NAME="PCorpOS"
BUILD_DIR=".build/debug"
APP_BUNDLE=".build/${APP_NAME}.app"
BUNDLE_ID="media.alphamode.pcorpos"

PYTHON_VERSION="3.12.13"
PYTHON_BUILD_TAG="20260718"
PYTHON_RUNTIME_CACHE=".build/python-runtime"
PYTHON_RELEASE_ASSET="cpython-${PYTHON_VERSION}+${PYTHON_BUILD_TAG}-aarch64-apple-darwin-install_only_stripped.tar.gz"
PYTHON_RELEASE_URL="https://github.com/astral-sh/python-build-standalone/releases/download/${PYTHON_BUILD_TAG}/${PYTHON_RELEASE_ASSET}"

echo "Building ${APP_NAME}..."
swift build

# --- Stage 2: prepare the embedded Python runtime (cached — only download/
# install once; re-run install if backend/uv.lock changed since last time). ---
if [ ! -x "$PYTHON_RUNTIME_CACHE/bin/python3.12" ]; then
    echo "Downloading relocatable Python ${PYTHON_VERSION} (python-build-standalone)..."
    mkdir -p "$PYTHON_RUNTIME_CACHE"
    curl -L -o /tmp/pcorpos-python-runtime.tar.gz "$PYTHON_RELEASE_URL"
    tar xzf /tmp/pcorpos-python-runtime.tar.gz -C "$PYTHON_RUNTIME_CACHE" --strip-components=1
    rm /tmp/pcorpos-python-runtime.tar.gz
fi

LOCK_HASH_FILE="$PYTHON_RUNTIME_CACHE/.uv-lock-hash"
CURRENT_LOCK_HASH="$(shasum -a 256 "$REPO_ROOT/backend/uv.lock" | awk '{print $1}')"
if [ ! -f "$LOCK_HASH_FILE" ] || [ "$(cat "$LOCK_HASH_FILE")" != "$CURRENT_LOCK_HASH" ]; then
    echo "Installing locked backend dependencies into the embedded runtime..."
    (cd "$REPO_ROOT/backend" && ~/Library/Python/3.9/bin/uv export --no-hashes --format requirements-txt) \
        > /tmp/pcorpos-requirements.txt
    "$PYTHON_RUNTIME_CACHE/bin/python3.12" -m pip install --quiet --no-cache-dir -r /tmp/pcorpos-requirements.txt
    rm /tmp/pcorpos-requirements.txt
    echo "$CURRENT_LOCK_HASH" > "$LOCK_HASH_FILE"
else
    echo "Embedded runtime dependencies already match backend/uv.lock, skipping install."
fi

echo "Compiling backend shim..."
clang -O2 \
    -DPCORPOS_BACKEND_SOURCE_PATH="\"${REPO_ROOT}/backend\"" \
    -o "$PYTHON_RUNTIME_CACHE/../PCorpOSBackend" \
    backend_shim.c

echo "Assembling ${APP_BUNDLE}..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cp "$BUILD_DIR/$APP_NAME" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"
cp ".build/PCorpOSBackend" "$APP_BUNDLE/Contents/MacOS/PCorpOSBackend"

# Real resource files go in Contents/Resources/ — the standard, codesign-
# friendly location. NOT SPM's generated PCorpOS_PCorpOS.bundle: that
# resolves (per its own generated accessor) to Bundle.main.bundleURL, which
# for a real .app is the bundle's root directory — and codesign rejects
# anything sitting there besides Contents/ ("unsealed contents present in
# the bundle root", confirmed directly). AppResources.swift checks
# Contents/Resources/ first for exactly this reason, falling back to
# Bundle.module only for `swift run` dev mode.
cp -R "$BUILD_DIR/${APP_NAME}_${APP_NAME}.bundle/"* "$APP_BUNDLE/Contents/Resources/"

echo "Embedding Python runtime (this copy can be slow, ~115MB)..."
cp -R "$PYTHON_RUNTIME_CACHE" "$APP_BUNDLE/Contents/Resources/python"
rm -f "$APP_BUNDLE/Contents/Resources/python/.uv-lock-hash"

# Stage 3: the LaunchAgent registration plist. SMAppService.agent(plistName:)
# requires this exact location, and the target executable must be co-located
# in this same bundle's Contents/MacOS/ (a real, checked API requirement).
# ProgramArguments[0] must be a REAL PATH, not just the bare executable
# name — confirmed directly via Console/unified-log output after the bare
# name failed: launchd's posix_spawn does its own plain POSIX exec path
# resolution (PATH-search for a bare name, no slash), it does NOT get
# rewritten to be bundle-relative by SMAppService/BTM first. An absolute
# path is the simplest fix that's guaranteed correct — consistent with the
# same "still single-machine, not distributed" scope already decided for
# the shim's PYTHONPATH in stage 2. Logs to /tmp since a launchd-managed
# process has no terminal to inherit.
BACKEND_LABEL="media.alphamode.pcorpos.backend"
ABS_APP_BUNDLE="$(pwd)/$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/Library/LaunchAgents"
cat > "$APP_BUNDLE/Contents/Library/LaunchAgents/${BACKEND_LABEL}.plist" << AGENTPLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${BACKEND_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${ABS_APP_BUNDLE}/Contents/MacOS/PCorpOSBackend</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/tmp/pcorpos-backend.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/pcorpos-backend.log</string>
</dict>
</plist>
AGENTPLIST

cat > "$APP_BUNDLE/Contents/Info.plist" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key>
    <string>P Corp OS</string>
    <key>CFBundleIdentifier</key>
    <string>${BUNDLE_ID}</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>CFBundleShortVersionString</key>
    <string>0.1</string>
    <key>CFBundleExecutable</key>
    <string>${APP_NAME}</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>LSMinimumSystemVersion</key>
    <string>14.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>NSCalendarsFullAccessUsageDescription</key>
    <string>Frank shows your upcoming events in the Calendar section and War Room's Today's Agenda.</string>
</dict>
</plist>
PLIST

echo "Ad-hoc signing..."
# codesign rejects any resource fork / Finder-info extended attributes on
# copied files ("resource fork, Finder information, or similar detritus not
# allowed") — some of the source resource files (already in the repo,
# original artwork) carry them. Strip before signing, not after — signing
# then stripping would invalidate the just-created signature.
xattr -cr "$APP_BUNDLE"
codesign --force --sign - "$APP_BUNDLE"

echo "Done: $APP_BUNDLE"
echo "Backend shim: Contents/MacOS/PCorpOSBackend, registerable via Settings → Launch at Login (SMAppService, stage 3)"
