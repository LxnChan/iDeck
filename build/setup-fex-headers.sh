#!/bin/bash
# Generate FEXCore compile-time configuration and IR headers into FEX/build-ios/include
set -eu

R="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

mkdir -p "$R/FEX/build-ios/include/FEXCore/Config"
mkdir -p "$R/FEX/build-ios/include/FEXCore/IR"

echo "==> Generating FEXCore configuration headers..."
python3 "$R/FEX/FEXCore/Scripts/config_generator.py" \
    "$R/FEX/FEXCore/Source/Interface/Config/Config.json.in" \
    "$R/FEX/build-ios/include/FEXCore/Config/ConfigValues.inl" \
    "$R/FEX/build-ios/FEX.1" \
    "$R/FEX/build-ios/include/FEXCore/Config/ConfigOptions.inl"

echo "==> Generating FEXCore IR defines..."
python3 "$R/FEX/FEXCore/Scripts/json_ir_generator.py" \
    "$R/FEX/FEXCore/Source/Interface/IR/IR.json" \
    "$R/FEX/build-ios/include/FEXCore/IR/IRDefines.inc" \
    "$R/FEX/build-ios/include/FEXCore/IR/IRDefines_Dispatch.inc"

echo "==> FEXCore generated headers are ready in FEX/build-ios/include."
