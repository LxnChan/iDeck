/* SPDX-License-Identifier: LGPL-2.1-or-later
 * Copyright 2026 LxnChan
 * A Steam-session-only load policy; never edits Valve's files.
 */
#ifndef IDECK_STEAM_CRASHHANDLER_POLICY_H
#define IDECK_STEAM_CRASHHANDLER_POLICY_H

#include <stddef.h>
#include <stdint.h>

static inline int ideck_block_steam_crashhandler( const uint16_t *name, size_t length,
                                                int steam_session, int disabled )
{
    static const char target[] = "crashhandler64.dll";
    size_t start = 0, i, count;
    if (!name || !steam_session || !disabled) return 0;
    for (i = 0; i < length; ++i)
        if (name[i] == '\\' || name[i] == '/') start = i + 1;
    count = length - start;
    if (count != sizeof(target) - 1 && count != sizeof(target) - 5) return 0;
    for (i = 0; i < count; ++i)
    {
        uint16_t c = name[start + i];
        if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
        if (c != (unsigned char)target[i]) return 0;
    }
    return 1;
}

#endif
