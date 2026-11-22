// SPDX-License-Identifier: GPL-3.0-or-later
// Madeira Converter Exception: see LICENSE-EXCEPTION.md

import SwiftUI
import UniformTypeIdentifiers

struct ExternalStorageIndicator: View {
    @ObservedObject private var storage = ExternalStorage.shared
    var body: some View {
        if let status = storage.connectionIndicator {
            Image(systemName: "externaldrive.fill")
                .foregroundStyle(color(status))
                .accessibilityLabel(status.label)
                .help(status.label)
        }
    }
    private func color(_ status: ExternalStorage.ConnectionIndicator) -> Color {
        switch status {
        case .connected: return .green
        case .partial: return .yellow
        case .unavailable: return .red
        }
    }
}

struct ExternalStorageSection: View {
    @ObservedObject private var storage = ExternalStorage.shared
    var body: some View {
        Section("Storage") {
            NavigationLink { ExternalStorageSettings() } label: {
                Label("External storage", systemImage: "externaldrive")
            }
            if !storage.records.isEmpty {
                Text("\(storage.records.filter { storage.statuses[$0.id]?.ready == true }.count) of \(storage.records.count) external folders connected")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
    }
}

struct ExternalStorageSettings: View {
    @ObservedObject private var storage = ExternalStorage.shared
    @State private var choosing = false
    @State private var remove: UUID?
    var body: some View {
        Form {
            Section {
                Button { choosing = true } label: { Label("Add or reauthorize folder", systemImage: "folder.badge.plus") }
                    .disabled(!storage.canChange)
                if storage.busy { ProgressView("Checking folder access…") }
                if !storage.canChange && !storage.busy {
                    Text("Stop games, downloads, and save sync before changing storage.").font(.caption).foregroundStyle(.secondary)
                }
            } footer: {
                Text("Choose a writable folder on a connected external drive. Its contents appear under C:\\External. Files stay on that drive. Reauthorizing the same folder keeps its game paths.")
            }
            ForEach(storage.records) { record in
                Section(record.name) {
                    let status = storage.statuses[record.id] ?? .init()
                    Label(status.message, systemImage: status.ready ? "externaldrive.badge.checkmark" : "externaldrive.badge.exclamationmark")
                        .foregroundStyle(status.ready ? Color.primary : .secondary)
                    Text("C:\\" + record.relativeRoot.replacingOccurrences(of: "/", with: "\\"))
                        .font(.caption.monospaced()).textSelection(.enabled)
                    if let bytes = status.freeBytes, status.ready {
                        LabeledContent("Free on this drive", value: ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file))
                    }
                    if record.enabled {
                        Button("Safely disconnect") { storage.disconnect(record.id) }.disabled(!storage.canChange)
                    } else {
                        Button("Reconnect") { storage.reconnect(record.id) }.disabled(!storage.canChange)
                    }
                    Button("Remove mapping", role: .destructive) { remove = record.id }.disabled(!storage.canChange)
                }
            }
            Section("Default for new Steam downloads") {
                Picker("Install location", selection: Binding(get: { storage.downloadLibrary }, set: { storage.downloadLibrary = $0 })) {
                    Text("Internal storage").tag(SteamInstallPaths.libraryRelative)
                    ForEach(storage.records) { record in
                        Text(record.name + (storage.statuses[record.id]?.ready == true ? "" : " (unavailable)"))
                            .tag(record.relativeRoot + "/steamapps")
                    }
                    if storage.downloadLibrary != SteamInstallPaths.libraryRelative,
                       !storage.records.contains(where: { $0.relativeRoot + "/steamapps" == storage.downloadLibrary }) {
                        Text("Removed mapping (choose a location)").tag(storage.downloadLibrary)
                    }
                }.disabled(!storage.canChange)
                Text("New downloads start with this default. You can choose another location for one download on its install page. Updates and unfinished downloads keep their original location; an unavailable drive never falls back to internal storage.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section {
                Button("Check connected folders") { storage.checkConnectedFolders() }
                    .disabled(storage.busy || storage.checkFeedback == .checking)
                switch storage.checkFeedback {
                case .idle: EmptyView()
                case .checking: ProgressView("Checking connected folders…")
                case .success(let date):
                    Label("Check successful", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
                    Text("Last checked \(date.formatted(date: .omitted, time: .shortened))")
                        .font(.caption).foregroundStyle(.secondary)
                case .failure(let message):
                    Label(message, systemImage: "exclamationmark.circle.fill").foregroundStyle(.orange)
                }
            } footer: {
                Text("Disconnect safely before unplugging. Removing a mapping keeps its files on the external drive. Saves stored beside a game also need that drive; Windows user folders remain in internal storage.")
            }
        }
        .navigationTitle("External storage")
        .fileImporter(isPresented: $choosing, allowedContentTypes: [.folder]) { result in
            switch result {
            case .success(let url): storage.add(url)
            case .failure(let error): storage.error = error.localizedDescription
            }
        }
        .confirmationDialog("Remove this mapping? External files are kept. Its games remain unavailable until the original folder is added again.",
                            isPresented: Binding(get: { remove != nil }, set: { if !$0 { remove = nil } }), titleVisibility: .visible) {
            Button("Remove mapping", role: .destructive) { if let remove { storage.disconnect(remove, remove: true) }; remove = nil }
        }
        .alert("External storage", isPresented: Binding(get: { storage.error != nil }, set: { if !$0 { storage.error = nil } })) {
            Button("OK", role: .cancel) { storage.error = nil }
        } message: { Text(storage.error ?? "") }
        .onAppear { storage.start(); storage.refresh(write: true) }
    }
}

/// Leave unavailable cards tappable so their details can explain how to recover.
struct ExternalGameAppearance: ViewModifier {
    let relative: String
    @ObservedObject private var storage = ExternalStorage.shared
    func body(content: Content) -> some View {
        let unavailable = DrivePaths.shared.problem(relative) != nil
        content.saturation(unavailable ? 0 : 1).opacity(unavailable ? 0.45 : 1)
            .overlay(alignment: .topTrailing) {
                if unavailable {
                    Label("Drive unavailable", systemImage: "externaldrive.badge.exclamationmark")
                        .font(.caption2).padding(5).background(.regularMaterial, in: RoundedRectangle(cornerRadius: 6)).allowsHitTesting(false)
                }
            }
    }
}
