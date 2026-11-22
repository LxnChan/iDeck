/* SPDX-License-Identifier: GPL-3.0-or-later
 * Madeira Converter Exception: see LICENSE-EXCEPTION.md
 * Extract only a pinned runtime from the user's verified Microsoft download.
 * Never execute the redistributable or replace unrelated Wine system DLLs.
 */
#ifndef UNICODE
#define UNICODE 1
#endif
#ifndef _UNICODE
#define _UNICODE 1
#endif
#include <windows.h>
#include <bcrypt.h>
#include <fdi.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>

static const char package_hash[] = "c2eb91d9c4448d50e46a32fecbcc3b418706d002beab9b5f4981de552098cee7";
static const char runtime_hash[] = "ec63a85030c60716acdcf060abfaa95a6a3528631622fa60e7d17fbea2f751f9";
static const unsigned char *input;
static size_t input_size, output_size, output_pos;
struct memory_file { size_t position; };
static unsigned char *output;
static const char *wanted;

static int hash_ok(const void *bytes, size_t size, const char *expected)
{
    BCRYPT_ALG_HANDLE algorithm = NULL;
    BCRYPT_HASH_HANDLE hash = NULL;
    unsigned char digest[32];
    char text[65];
    int ok = 0;
    if (size > 8 * 1024 * 1024 || BCryptOpenAlgorithmProvider(&algorithm, BCRYPT_SHA256_ALGORITHM, NULL, 0)) return 0;
    if (!BCryptCreateHash(algorithm, &hash, NULL, 0, NULL, 0, 0) &&
        !BCryptHashData(hash, (PUCHAR)bytes, (ULONG)size, 0) &&
        !BCryptFinishHash(hash, digest, sizeof(digest), 0))
    {
        for (unsigned i = 0; i < sizeof(digest); ++i) sprintf(text + i * 2, "%02x", digest[i]);
        ok = !strcmp(text, expected);
    }
    if (hash) BCryptDestroyHash(hash);
    BCryptCloseAlgorithmProvider(algorithm, 0);
    return ok;
}

static unsigned char *read_file(const wchar_t *path, size_t *size)
{
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    LARGE_INTEGER length;
    DWORD got;
    unsigned char *bytes = NULL;
    *size = 0;
    if (file == INVALID_HANDLE_VALUE) return NULL;
    if (GetFileSizeEx(file, &length) && length.QuadPart > 0 && length.QuadPart <= 8 * 1024 * 1024)
    {
        bytes = malloc((size_t)length.QuadPart);
        if (bytes && ReadFile(file, bytes, (DWORD)length.QuadPart, &got, NULL) && got == length.QuadPart) *size = got;
        else { free(bytes); bytes = NULL; }
    }
    CloseHandle(file);
    return bytes;
}

static void *DIAMONDAPI alloc_mem(ULONG size) { return malloc(size); }
static void DIAMONDAPI free_mem(void *ptr) { free(ptr); }
static INT_PTR DIAMONDAPI open_mem(char *name, int flags, int mode)
{
    (void)flags; (void)mode;
    if (strcmp(name, "memory.cab")) return -1;
    struct memory_file *file = calloc(1, sizeof(*file));
    return file ? (INT_PTR)file : -1;
}
static UINT DIAMONDAPI read_mem(INT_PTR file, void *data, UINT count)
{
    struct memory_file *source = (struct memory_file *)file;
    if (!source || file == 2 || source->position > input_size) return (UINT)-1;
    if (count > input_size - source->position) count = (UINT)(input_size - source->position);
    memcpy(data, input + source->position, count); source->position += count;
    return count;
}
static UINT DIAMONDAPI write_mem(INT_PTR file, void *data, UINT count)
{
    if (file != 2 || output_pos > output_size || count > output_size - output_pos) return (UINT)-1;
    memcpy(output + output_pos, data, count); output_pos += count;
    return count;
}
static int DIAMONDAPI close_mem(INT_PTR file) { if (file != 2) free((void *)file); return 0; }
static LONG DIAMONDAPI seek_mem(INT_PTR file, LONG distance, int origin)
{
    int64_t next = distance;
    struct memory_file *source = (struct memory_file *)file;
    if (!source || file == 2) return -1;
    if (origin == SEEK_CUR) next += source->position;
    else if (origin == SEEK_END) next += input_size;
    else if (origin != SEEK_SET) return -1;
    if (next < 0 || (uint64_t)next > input_size) return -1;
    source->position = (size_t)next;
    return (LONG)next;
}
static INT_PTR DIAMONDAPI notify(FDINOTIFICATIONTYPE type, PFDINOTIFICATION event)
{
    if (type == fdintNEXT_CABINET || type == fdintPARTIAL_FILE) return -1;
    if (type == fdintCLOSE_FILE_INFO) return output_pos == output_size;
    if (type != fdintCOPY_FILE || strcmp(event->psz1, wanted)) return 0;
    if (output || event->cb <= 0 || event->cb > 8 * 1024 * 1024) return -1;
    output_size = event->cb; output_pos = 0;
    output = malloc(output_size);
    return output ? 2 : -1;
}

/* The whole PE has already been hash checked. Locate its embedded cabinet;
 * the FDI callbacks expose only memory and the one exact requested filename. */
static unsigned char *extract(const unsigned char *pe, size_t size, const char *name, size_t *length)
{
    ERF error = {0};
    HFDI cabinet;
    unsigned char *result = NULL;
    input = NULL;
    for (size_t at = 0; at + 36 <= size; ++at)
    {
        uint32_t count;
        if (memcmp(pe + at, "MSCF\0\0\0\0", 8)) continue;
        memcpy(&count, pe + at + 8, 4);
        if (count >= 36 && count <= size - at) { input = pe + at; input_size = count; break; }
    }
    if (!input) return NULL;
    wanted = name; output = NULL; output_size = output_pos = 0;
    cabinet = FDICreate(alloc_mem, free_mem, open_mem, read_mem, write_mem, close_mem, seek_mem, cpuUNKNOWN, &error);
    if (cabinet)
    {
        if (FDICopy(cabinet, "memory.cab", "", 0, notify, NULL, NULL) && output && output_pos == output_size)
        { result = output; *length = output_size; }
        FDIDestroy(cabinet);
    }
    if (!result) fprintf(stderr, "[legacy-runtime] cabinet extraction failed: %s (FDI=%d)\n", name, error.erfOper);
    if (!result) free(output);
    output = NULL;
    return result;
}

static int install(const wchar_t *package, const wchar_t *destination)
{
    size_t size = 0, nested_size = 0, dll_size = 0;
    unsigned char *bytes = read_file(package, &size), *nested = NULL, *dll = NULL, *existing = NULL;
    wchar_t temporary[32768];
    DWORD written, attributes = GetFileAttributesW(destination);
    HANDLE file;
    int code = 1;
    if (!bytes || !hash_ok(bytes, size, package_hash)) { fprintf(stderr, "[legacy-runtime] package hash failed\n"); goto done; }
    nested = extract(bytes, size, "vcredist.exe", &nested_size);
    if (!nested) goto done;
    dll = extract(nested, nested_size, "mfc42.dll", &dll_size);
    if (!dll || !hash_ok(dll, dll_size, runtime_hash)) { fprintf(stderr, "[legacy-runtime] DLL extraction/hash failed\n"); goto done; }
    if (attributes != INVALID_FILE_ATTRIBUTES)
    {
        if (attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) { code = 2; goto done; }
        existing = read_file(destination, &size);
        code = existing && hash_ok(existing, size, runtime_hash) ? 0 : 2;
        goto done;
    }
    if (wcslen(destination) > 32000) goto done;
    swprintf(temporary, 32768, L"%ls.madeira-%lu.tmp", destination, GetCurrentProcessId());
    file = CreateFileW(temporary, GENERIC_WRITE, 0, NULL, CREATE_NEW, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file == INVALID_HANDLE_VALUE) goto done;
    code = WriteFile(file, dll, (DWORD)dll_size, &written, NULL) && written == dll_size && FlushFileBuffers(file) ? 0 : 1;
    CloseHandle(file);
    /* MoveFile refuses an existing destination, including a racing installer. */
    if (!code && !MoveFileW(temporary, destination)) code = 2;
    if (code) DeleteFileW(temporary);
done:
    free(existing); free(dll); free(nested); free(bytes);
    return code;
}

/* Standard Windows argv quoting; never interpret application arguments as a
 * shell program. This also preserves arguments of an existing cmd /c launch. */
static int append_argument(wchar_t *command, size_t *used, const wchar_t *argument)
{
    size_t slashes = 0;
    #define EMIT(c) do { if (*used >= 32765) return 0; command[(*used)++] = (c); } while (0)
    if (*used) EMIT(L' ');
    EMIT(L'"');
    for (;; ++argument)
    {
        if (*argument == L'\\') { ++slashes; continue; }
        if (*argument == L'"' || !*argument)
            for (size_t i = 0; i < slashes * 2; ++i) EMIT(L'\\');
        else for (size_t i = 0; i < slashes; ++i) EMIT(L'\\');
        slashes = 0;
        if (!*argument) break;
        if (*argument == L'"') EMIT(L'\\');
        EMIT(*argument);
    }
    EMIT(L'"'); command[*used] = 0;
    #undef EMIT
    return 1;
}

int wmain(int argc, wchar_t **argv)
{
    int code;
    HANDLE report;
    DWORD written;
    if (argc < 4 || (argc > 4 && (argc < 6 || wcscmp(argv[4], L"--launch")))) return 64;
    code = install(argv[1], argv[2]);
    report = CreateFileW(argv[3], GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (report != INVALID_HANDLE_VALUE)
    {
        const char *message = code == 0 ? "ok\n" : code == 2 ? "conflict\n" : "invalid-package\n";
        WriteFile(report, message, (DWORD)strlen(message), &written, NULL);
        CloseHandle(report);
    }
    fprintf(stderr, "[legacy-runtime] mfc42 install result=%d\n", code);
    if (!code && argc > 4)
    {
        wchar_t command[32768] = {0};
        size_t used = 0;
        STARTUPINFOW startup = {0};
        PROCESS_INFORMATION process;
        DWORD status = 1;
        for (int i = 5; i < argc; ++i) if (!append_argument(command, &used, argv[i])) return 65;
        startup.cb = sizeof(startup);
        GetStartupInfoW(&startup);
        if (!CreateProcessW(NULL, command, NULL, NULL, TRUE, 0, NULL, NULL, &startup, &process)) return 66;
        CloseHandle(process.hThread);
        WaitForSingleObject(process.hProcess, INFINITE);
        GetExitCodeProcess(process.hProcess, &status);
        CloseHandle(process.hProcess);
        return (int)status;
    }
    return code;
}
