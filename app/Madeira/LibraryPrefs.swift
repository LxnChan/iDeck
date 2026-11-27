//
//  LibraryPrefs.swift
//  Madeira
//
//  madeira-bcd: a game's own launch switches, kept by its Windows path (AVX,
//  Report an NVIDIA GPU, Wine's C++ runtime), which every launch of the game
//  exports (BCDLaunch, LibraryBCD.swift).
//

import Foundation

enum NvidiaGPUModel: String, CaseIterable, Identifiable {
    case rtx2060 = "1F08"
    case rtx3060 = "2544"
    case rtx4060 = "2882"
    case rtx4070 = "2786"
    case rtx4080 = "2704"
    case rtx4090 = "2684"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .rtx2060: "GeForce RTX 2060"
        case .rtx3060: "GeForce RTX 3060"
        case .rtx4060: "GeForce RTX 4060"
        case .rtx4070: "GeForce RTX 4070"
        case .rtx4080: "GeForce RTX 4080"
        case .rtx4090: "GeForce RTX 4090"
        }
    }

    static let defaultModel: NvidiaGPUModel = .rtx3060
}

/// Per-title launch switches that are not command-line arguments, keyed by
/// the game's Windows path.
enum LibraryPrefs {
    private static let avxKey = "madeira.library.avx"
    private static let vcrtKey = "madeira.library.wineVCRT"
    private static let nvidiaKey = "madeira.library.nvidia"
    private static let nvidiaModelKey = "madeira.library.nvidiaModel"

    private static func dict<T>(_ key: String) -> [String: T] {
        (UserDefaults.standard.dictionary(forKey: key) as? [String: T]) ?? [:]
    }

    private static func store<T>(_ value: T?, _ key: String, _ field: String) {
        var all: [String: T] = dict(key)
        all[field] = value
        UserDefaults.standard.set(all, forKey: key)
    }

    static func avx(_ windowsPath: String) -> Bool { (dict(avxKey) as [String: Bool])[windowsPath] ?? false }
    static func setAVX(_ on: Bool, for windowsPath: String) { store(on ? true : nil, avxKey, windowsPath) }

    static func wineVCRT(_ windowsPath: String) -> Bool { (dict(vcrtKey) as [String: Bool])[windowsPath] ?? false }
    static func setWineVCRT(_ on: Bool, for windowsPath: String) { store(on ? true : nil, vcrtKey, windowsPath) }

    static func nvidia(_ windowsPath: String) -> Bool { (dict(nvidiaKey) as [String: Bool])[windowsPath] ?? false }
    static func setNvidia(_ on: Bool, for windowsPath: String) { store(on ? true : nil, nvidiaKey, windowsPath) }

    static func nvidiaModel(_ windowsPath: String) -> NvidiaGPUModel {
        guard let value = (dict(nvidiaModelKey) as [String: String])[windowsPath],
              let model = NvidiaGPUModel(rawValue: value) else { return .defaultModel }
        return model
    }

    static func setNvidiaModel(_ model: NvidiaGPUModel, for windowsPath: String) {
        store(model.rawValue == NvidiaGPUModel.defaultModel.rawValue ? nil : model.rawValue,
              nvidiaModelKey, windowsPath)
    }

    /// FNV-1a over a string: stable across launches, unlike String.hashValue.
    /// Names a game's config file (GameProfiles.swift) and fingerprints the
    /// recommended settings Madeira wrote (GameRecommendationsApply.swift).
    static func stableHash(_ s: String) -> UInt64 {
        var h: UInt64 = 0xcbf29ce484222325
        for b in s.utf8 { h = (h ^ UInt64(b)) &* 0x100000001b3 }
        return h
    }
}
