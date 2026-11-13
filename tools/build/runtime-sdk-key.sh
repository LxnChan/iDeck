#!/usr/bin/env bash
# Scope native runtime caches to the actual Apple compiler and SDKs.
set -euo pipefail
key=$({
  xcodebuild -version
  xcrun --sdk iphoneos --show-sdk-version
  xcrun --sdk iphoneos --show-sdk-build-version
  xcrun --sdk macosx --show-sdk-version
  xcrun --sdk macosx --show-sdk-build-version
  xcrun clang --version
  uname -sm
  env | LC_ALL=C sort | awk -F= '$1 ~ /^(CC|CXX|CFLAGS|CXXFLAGS|CPPFLAGS|LDFLAGS|SDKROOT|IPHONEOS_DEPLOYMENT_TARGET|MACOSX_DEPLOYMENT_TARGET|DXMT_METAL_STD)$/'
} | shasum -a 256 | cut -c1-20)
printf 'key=%s\n' "$key" >> "$GITHUB_OUTPUT"
