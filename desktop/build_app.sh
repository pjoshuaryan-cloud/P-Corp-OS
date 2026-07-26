#!/bin/bash
# Stage 1 of SMAppService packaging (TECH_STACK.md): turns the raw SPM
# executable into a real .app bundle. This project has run via `swift
# build`/`swift run` from day one (no Xcode installed, only command-line
# tools) — that's the same root cause behind the activation-policy/Dock-icon
# workarounds already in ContentView.swift, and the EventKit/
# UNUserNotificationCenter failures worked around with AppleScript. A real
# bundle doesn't remove those workarounds (not touched here, on purpose —
# a separate, deliberate cleanup once this is proven stable), but it's the
# actual prerequisite SMAppService needs to register a persistent LaunchAgent
# at all.
#
# Re-run this after every code change instead of `swift build` when you want
# to test the bundled form specifically. `swift run` during normal
# development is unaffected and still works exactly as before.
set -euo pipefail

cd "$(dirname "$0")"

APP_NAME="PCorpOS"
BUILD_DIR=".build/debug"
APP_BUNDLE=".build/${APP_NAME}.app"
BUNDLE_ID="media.alphamode.pcorpos"

echo "Building ${APP_NAME}..."
swift build

echo "Assembling ${APP_BUNDLE}..."
rm -rf "$APP_BUNDLE"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources"

cp "$BUILD_DIR/$APP_NAME" "$APP_BUNDLE/Contents/MacOS/$APP_NAME"

# Real resource files go in Contents/Resources/ — the standard, codesign-
# friendly location. NOT SPM's generated PCorpOS_PCorpOS.bundle: that
# resolves (per its own generated accessor) to Bundle.main.bundleURL, which
# for a real .app is the bundle's root directory — and codesign rejects
# anything sitting there besides Contents/ ("unsealed contents present in
# the bundle root", confirmed directly). AppResources.swift checks
# Contents/Resources/ first for exactly this reason, falling back to
# Bundle.module only for `swift run` dev mode.
cp -R "$BUILD_DIR/${APP_NAME}_${APP_NAME}.bundle/"* "$APP_BUNDLE/Contents/Resources/"

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
