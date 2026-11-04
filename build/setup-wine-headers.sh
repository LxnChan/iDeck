#!/bin/bash
set -eu

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
WINE_SRC="$REPO_ROOT/wine"
WINE_BUILD="$WINE_SRC/build-macos"

echo "==> Setting up Wine host headers in $WINE_BUILD..."

mkdir -p "$WINE_BUILD/include"
mkdir -p "$WINE_BUILD/dlls/ntdll"
mkdir -p "$WINE_BUILD/dlls/win32u"

# Try running configure if possible
if [ ! -f "$WINE_BUILD/include/config.h" ] && [ -f "$WINE_SRC/configure" ]; then
    echo "Attempting Wine configure for host tree..."
    (
        cd "$WINE_BUILD"
        ../configure --enable-archs=none --without-mingw --without-x \
            --without-freetype --without-fontconfig --without-gnutls --disable-tests \
            > "$WINE_BUILD/configure.log" 2>&1 || true
    )
fi

# If config.h was not generated or configure failed, write out comprehensive macOS/iOS config.h
if [ ! -f "$WINE_BUILD/include/config.h" ]; then
    echo "Creating fallback Darwin config.h..."
    cat > "$WINE_BUILD/include/config.h" << 'EOF'
/* include/config.h. Staged Darwin/iOS configuration for Wine build tree. */
#ifndef __WINE_CONFIG_H
#define __WINE_CONFIG_H

#define PACKAGE_NAME "Wine"
#define PACKAGE_TARNAME "wine"
#define PACKAGE_VERSION "11.4"
#define PACKAGE_STRING "Wine 11.4"
#define PACKAGE_BUGREPORT "wine-devel@winehq.org"
#define PACKAGE_URL "https://www.winehq.org"

#define STDC_HEADERS 1
#define HAVE_SYS_TYPES_H 1
#define HAVE_SYS_STAT_H 1
#define HAVE_STDLIB_H 1
#define HAVE_STRING_H 1
#define HAVE_MEMORY_H 1
#define HAVE_STRINGS_H 1
#define HAVE_INTTYPES_H 1
#define HAVE_STDINT_H 1
#define HAVE_UNISTD_H 1
#define HAVE_SYS_TIME_H 1
#define HAVE_SYS_SOCKET_H 1
#define HAVE_NETINET_IN_H 1
#define HAVE_ARPA_INET_H 1
#define HAVE_DLFCN_H 1
#define HAVE_PTHREAD_H 1
#define HAVE_MACH_MACH_H 1
#define HAVE_POLL_H 1
#define HAVE_SYS_POLL_H 1
#define HAVE_SYS_MMAN_H 1
#define HAVE_SYS_UIO_H 1
#define HAVE_SYS_MOUNT_H 1
#define HAVE_SYS_PARAM_H 1
#define HAVE_SYS_RESOURCE_H 1
#define HAVE_SYS_SYSCTL_H 1
#define HAVE_SYS_WAIT_H 1
#define HAVE_SYS_UN_H 1
#define HAVE_SYS_EVENT_H 1
#define HAVE_KQUEUE 1
#define HAVE_GETPAGESIZE 1
#define HAVE_MMAP 1
#define HAVE_SIGACTION 1
#define HAVE_SIGPROCMASK 1
#define HAVE_SPAWN_H 1
#define HAVE_POSIX_SPAWN 1
#define HAVE_CLOCK_GETTIME 1
#define HAVE_GETTIMEOFDAY 1
#define HAVE_STRUCT_STAT_ST_BIRTHTIME 1
#define HAVE_STRUCT_STAT_ST_FLAGS 1
#define HAVE_STRUCT_SOCKADDR_UN_SUN_LEN 1
#define HAVE_SCHED_H 1
#define HAVE_PWD_H 1
#define HAVE_SYS_QUEUE_H 1
#define HAVE_SYS_SIGNAL_H 1
#define HAVE_DIRENT_H 1

#endif /* __WINE_CONFIG_H */
EOF
fi

# Provide stub headers for IDL-generated COM headers if not present
for hdr in objidlbase.h objidl.h unknwn.h unknwnbase.h propidl.h propidlbase.h oaidl.h; do
    if [ ! -f "$WINE_BUILD/include/$hdr" ] && [ ! -f "$WINE_SRC/include/$hdr" ]; then
        echo "#pragma once" > "$WINE_BUILD/include/$hdr"
    fi
done

echo "Wine host headers ready at $WINE_BUILD/include/config.h"
