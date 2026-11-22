// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
#include <windows.h>

// Retain Wine's software-info export for legacy callers alongside upstream's
// four D3D8 exports. Wine returns S_OK without writing any output here.
extern "C" __declspec(dllexport) HRESULT WINAPI D3D8GetSWInfo()
{
    return S_OK;
}
