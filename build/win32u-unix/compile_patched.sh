#!/bin/bash
set -e

BUILD_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$BUILD_DIR/../.." && pwd)"
WINE_SRC="$REPO_ROOT/wine"
WINE_BUILD="$WINE_SRC/build-macos"
NTDLL_SHIMS="$REPO_ROOT/build/ntdll-unix/shims"
SDK=$(xcrun --sdk iphoneos --show-sdk-path)
OBJ_DIR="$BUILD_DIR/obj"
APP_LIB="$REPO_ROOT/app/Madeira/libwin32u_unix.a"

mkdir -p "$OBJ_DIR"

if [ ! -f "$WINE_BUILD/include/config.h" ]; then
    bash "$REPO_ROOT/build/setup-wine-headers.sh"
fi

echo "=== Compiling patched driver_ios.c ==="
xcrun -sdk iphoneos clang \
    -arch arm64 -isysroot "$SDK" -miphoneos-version-min=17.0 \
    -O2 -fPIC -fvisibility=hidden -fno-stack-protector -fno-strict-aliasing \
    -Wno-implicit-function-declaration -Wno-int-conversion \
    -include "$BUILD_DIR/config_ios.h" \
    -include "$REPO_ROOT/build/ntdll-unix/shims/wine_ios_exit.h" \
    -I"$BUILD_DIR" \
    -I"$WINE_BUILD/include" \
    -I"$NTDLL_SHIMS" \
    -I"$WINE_BUILD/dlls/win32u" -I"$WINE_SRC/dlls/win32u" \
    -I"$WINE_BUILD/include" -I"$WINE_SRC/include" \
    -D__WINESRC__ -D_WIN32U_ \
    -D_ACRTIMP= -DWINBASEAPI= \
    -DSYSTEMDLLPATH=\"\" \
    -DWINE_UNIX_LIB -DWINE_IOS=1 \
    -D__wine_unix_lib_init=win32u_unix_lib_init \
    -USONAME_LIBFREETYPE \
    -USONAME_LIBFONTCONFIG \
    -USONAME_LIBEGL \
    -USONAME_LIBVULKAN \
    -USONAME_LIBGNUTLS \
    -UHAVE_FT2BUILD_H \
    -c "$BUILD_DIR/driver_ios.c" -o "$OBJ_DIR/driver.o"

echo "=== Updating libwin32u_unix.a ==="
if [ ! -f "$OBJ_DIR/libwin32u_unix.a" ] && [ -f "$APP_LIB" ]; then
    cp "$APP_LIB" "$OBJ_DIR/libwin32u_unix.a"
fi

if [ -f "$OBJ_DIR/libwin32u_unix.a" ]; then
    ar d "$OBJ_DIR/libwin32u_unix.a" driver.o 2>/dev/null || true
    ar r "$OBJ_DIR/libwin32u_unix.a" "$OBJ_DIR/driver.o"
    cp "$OBJ_DIR/libwin32u_unix.a" "$APP_LIB"
    echo "Done! libwin32u_unix.a: $(wc -c < "$APP_LIB" | tr -d ' ') bytes"
else
    echo "ERROR: libwin32u_unix.a not found in $APP_LIB"
    exit 1
fi
