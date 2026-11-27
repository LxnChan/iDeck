//
//  LibraryBCD.swift
//  Madeira
//
//  madeira-bcd: this fork's per-game options inside upstream's library.
//
//  A game's madeira-bcd options are keyed by its Windows path: the switches in
//  LibraryPrefs (AVX, Wine's C++ runtime, NVIDIA) and the game's own config
//  file (GameProfiles.swift: any madeira.cfg key or env.NAME line).
//

import Foundation

/// What a launch exports on top of the exe, its arguments and its screen.
enum BCDLaunch {
    /// Direct game starts need the same rule as games created later by Steam.
    /// The actual initial executable keeps desktop/services routes from adding twice.
    static func appendInitialArguments(_ entry: LibraryEntry, initialProgramIsChild: Bool = false) throws {
        // Runtime preparation starts the original program as a child. Its
        // normal child-launch path will apply this same rule exactly once.
        guard !initialProgramIsChild, entry.desktop != true,
              let rule = ChildLaunchArguments(configuration: GameProfile(windowsPath: entry.windowsPath).text),
              let executable = getenv("MADEIRA_EXE"), let arguments = getenv("MADEIRA_ARGS") else { return }
        let original = String(cString: arguments)
        let combined = try rule.appending(to: original, executable: String(cString: executable))
        if combined != original { setenv("MADEIRA_ARGS", combined, 1) }
    }

    /// The switches every launch of a game applies. Everything is set or unset, so a
    /// previous launch's choice never leaks into this one.
    static func applyExtras(avx: Bool, wineVCRT: Bool, nvidia: Bool,
                            nvidiaModel: NvidiaGPUModel = .defaultModel, profile: GameProfile?) {
        if avx { setenv("MADEIRA_FEX_AVX", "1", 1) } else { unsetenv("MADEIRA_FEX_AVX") }
        if wineVCRT { setenv("MADEIRA_WINE_VCRT", "1", 1) } else { unsetenv("MADEIRA_WINE_VCRT") }
        var dxmtExtra: [String] = []
        if nvidia {
            setenv("DXMT_ENABLE_NVEXT", "1", 1)
            setenv("MADEIRA_NVIDIA_DEVICE_ID", nvidiaModel.rawValue, 1)
            // win32u registers the same selected NVIDIA PCI device as the
            // display adapter; ContentView merges this id into DXMT_CONFIG.
            dxmtExtra.append("dxgi.customDeviceId=\(nvidiaModel.rawValue)")
            // DXGI's output carries user32's monitor handle and user32's mode
            // list, so a game can find its monitor on the adapter. Default-on
            // in this fork until the build 222 switch to upstream, where both
            // became 32-bit-only switches; Ghost of Tsushima has said "No
            // installed graphics card ... monitor connected to it" on every
            // launch since (logs 2026-10-01 16:15 / 16:16 / 17:04; 2026-09-28
            // ran with both). A game file's env.NAME = 0 still wins.
            setenv("DXMT_WSI_MONITOR_IDENTITY", "1", 1)
            setenv("DXMT_WSI_MODE_TABLE", "1", 1)
        } else {
            unsetenv("DXMT_ENABLE_NVEXT")
            unsetenv("MADEIRA_NVIDIA_DEVICE_ID")
            unsetenv("DXMT_WSI_MONITOR_IDENTITY")
            unsetenv("DXMT_WSI_MODE_TABLE")
        }
        // The game's own settings (GameProfiles.swift).
        if let p = profile, p.hasSettings, let u = p.url {
            setenv("MADEIRA_CFG_GAME", u.path, 1)
        } else {
            unsetenv("MADEIRA_CFG_GAME")
        }
        if dxmtExtra.isEmpty { unsetenv("MADEIRA_DXMT_EXTRA") }
        else { setenv("MADEIRA_DXMT_EXTRA", dxmtExtra.joined(separator: ";"), 1)   /* DXMT splits on ";" */ }
    }

    /// A start from upstream's library: this game's madeira-bcd options. The
    /// FPS limit is the entry's (upstream's FPS picker, which offers 40 FPS too).
    static func applyLibrary(_ entry: LibraryEntry) {
        if entry.desktop == true {
            applyExtras(avx: false, wineVCRT: false, nvidia: false, profile: nil)
            return
        }
        let path = entry.windowsPath
        let profile = GameProfile(windowsPath: path)
        applyExtras(avx: LibraryPrefs.avx(path), wineVCRT: LibraryPrefs.wineVCRT(path),
                    nvidia: LibraryPrefs.nvidia(path), nvidiaModel: LibraryPrefs.nvidiaModel(path),
                    profile: profile)
        let program = path.split(separator: "\\").last.map(String.init) ?? path
        LogStore.shared.log("[bcd] library launch \(program): avx=\(LibraryPrefs.avx(path) ? 1 : 0) "
                            + "wine-vcrt=\(LibraryPrefs.wineVCRT(path) ? 1 : 0) nvidia=\(LibraryPrefs.nvidia(path) ? 1 : 0) "
                            + "nvidia-model=\(LibraryPrefs.nvidiaModel(path).rawValue) "
                            + "game-config=\(profile.hasSettings ? 1 : 0)")
    }
}
