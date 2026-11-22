// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md
// Run against the packaged d3d8.dll. Prints to the Wine session log on device.
#include <windows.h>
#include <d3d8.h>
#include <stdio.h>

static int fail(const char *operation, HRESULT status)
{
    printf("[d3d8-probe] FAIL %s hr=%08lx\n", operation, (unsigned long)status);
    return 1;
}

int main()
{
    HWND window = CreateWindowA("STATIC", "D3D8 compatibility probe", WS_OVERLAPPEDWINDOW,
                                0, 0, 64, 64, NULL, NULL, GetModuleHandleA(NULL), NULL);
    if (!window) return fail("CreateWindow", HRESULT_FROM_WIN32(GetLastError()));
    HMODULE module = GetModuleHandleA("d3d8.dll");
    const char *exports[] = {"Direct3DCreate8", "DebugSetMute", "ValidatePixelShader",
                             "ValidateVertexShader", "D3D8GetSWInfo"};
    for (const char *name : exports)
        if (!GetProcAddress(module, name)) return fail(name, E_NOINTERFACE);
    IDirect3D8 *d3d = Direct3DCreate8(D3D_SDK_VERSION);
    if (!d3d) return fail("Direct3DCreate8", E_FAIL);
    UINT adapters = d3d->GetAdapterCount();
    if (!adapters) return fail("GetAdapterCount", E_FAIL);
    D3DCAPS8 caps = {};
    HRESULT hr = d3d->GetDeviceCaps(0, D3DDEVTYPE_HAL, &caps);
    if (FAILED(hr)) return fail("GetDeviceCaps", hr);
    D3DPRESENT_PARAMETERS present = {};
    present.BackBufferWidth = present.BackBufferHeight = 64;
    present.BackBufferFormat = D3DFMT_X8R8G8B8;
    present.BackBufferCount = 1;
    present.SwapEffect = D3DSWAPEFFECT_DISCARD;
    present.hDeviceWindow = window;
    present.Windowed = TRUE;
    present.Flags = D3DPRESENTFLAG_LOCKABLE_BACKBUFFER;
    IDirect3DDevice8 *device = NULL;
    hr = d3d->CreateDevice(0, D3DDEVTYPE_HAL, window, D3DCREATE_SOFTWARE_VERTEXPROCESSING,
                           &present, &device);
    if (FAILED(hr)) return fail("CreateDevice", hr);
    // Exercise the fixed-function path used by early D3D8 engines.
    struct Vertex { float x, y, z, rhw; DWORD color; };
    const Vertex triangle[] = {{0, 0, .5f, 1, 0xffff0000},
                               {64, 0, .5f, 1, 0xffff0000},
                               {0, 64, .5f, 1, 0xffff0000}};
    device->SetRenderState(D3DRS_LIGHTING, FALSE);
    device->SetRenderState(D3DRS_CULLMODE, D3DCULL_NONE);
    hr = device->SetVertexShader(D3DFVF_XYZRHW | D3DFVF_DIFFUSE);
    if (FAILED(hr)) return fail("SetVertexShader(FVF)", hr);
    hr = device->Clear(0, NULL, D3DCLEAR_TARGET, 0xff003366, 1, 0);
    if (FAILED(hr)) return fail("Clear", hr);
    hr = device->BeginScene();
    if (FAILED(hr)) return fail("BeginScene", hr);
    hr = device->DrawPrimitiveUP(D3DPT_TRIANGLELIST, 1, triangle, sizeof(Vertex));
    if (FAILED(hr)) return fail("DrawPrimitiveUP", hr);
    hr = device->EndScene();
    if (FAILED(hr)) return fail("EndScene", hr);
    IDirect3DSurface8 *backbuffer = NULL;
    hr = device->GetBackBuffer(0, D3DBACKBUFFER_TYPE_MONO, &backbuffer);
    if (FAILED(hr)) return fail("GetBackBuffer", hr);
    D3DLOCKED_RECT pixels = {};
    hr = backbuffer->LockRect(&pixels, NULL, D3DLOCK_READONLY);
    if (FAILED(hr)) return fail("LockRect", hr);
    DWORD inside = ((const DWORD *)((const char *)pixels.pBits + 8 * pixels.Pitch))[8] & 0xffffff;
    DWORD outside = ((const DWORD *)((const char *)pixels.pBits + 56 * pixels.Pitch))[56] & 0xffffff;
    backbuffer->UnlockRect();
    printf("[d3d8-probe] adapters=%u modes=%u vs=%lx ps=%lx inside=%06lx outside=%06lx\n",
           adapters, d3d->GetAdapterModeCount(0), (unsigned long)caps.VertexShaderVersion,
           (unsigned long)caps.PixelShaderVersion, (unsigned long)inside, (unsigned long)outside);
    backbuffer->Release();
    device->Release();
    d3d->Release();
    DestroyWindow(window);
    if (inside != 0xff0000 || outside != 0x003366) return fail("pixel readback", E_FAIL);
    puts("[d3d8-probe] PASS exports, enumeration, device, fixed-function draw and readback");
    return 0;
}
