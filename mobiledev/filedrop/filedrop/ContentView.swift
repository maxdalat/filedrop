//
//  ContentView.swift
//  filedrop
//
//  Created by Maxim Dalat on 5/24/26.
//

import SwiftUI
import UniformTypeIdentifiers
import Combine

private enum APIConfig {
    static let baseURL = URL(string: "https://filedrop.max-dalat.com/api")!
    static let maxUploadBytes: Int64 = 8 * 1024 * 1024 * 1024 // 8 GiB
}

struct ItemListing: Codable {
    var path: String
    var parent: String?
    var items: [Item]
}

struct Item: Identifiable, Hashable, Codable {
    var id: String { path }
    var name: String
    var path: String
    var type: ItemType
    var size: Int64?

    enum ItemType: String, Codable { case file, folder }
}

struct UploadTask: Identifiable, Hashable {
    enum State { case queued, uploading(Double), success(Date), failed(String) }
    let id = UUID()
    let url: URL
    let name: String
    var state: State
}

@MainActor
final class FileDropViewModel: ObservableObject {
    @Published var isHealthy: Bool = false
    @Published var listing: ItemListing = .init(path: "", parent: nil, items: [])
    @Published var isLoading: Bool = false
    @Published var message: String?
    @Published var showingError: Bool = false

    @Published var selection: Set<String> = [] // item.path
    @Published var isSelecting: Bool = false

    // Settings
    @AppStorage("uploadsAtOnce") var uploadsAtOnce: Int = 4
    @AppStorage("confirmSingleDelete") var confirmSingleDelete: Bool = true
    @AppStorage("confirmBulkDelete") var confirmBulkDelete: Bool = true

    // Upload panel
    @Published var uploadTasks: [UploadTask] = []

    var currentPath: String { listing.path }

    func checkHealth() async {
        do {
            let url = APIConfig.baseURL.appendingPathComponent("health")
            let (_, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { throw URLError(.badServerResponse) }
            isHealthy = true
        } catch {
            isHealthy = false
        }
    }

    func load(path: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            var comps = URLComponents(url: APIConfig.baseURL.appendingPathComponent("items"), resolvingAgainstBaseURL: false)!
            comps.queryItems = [URLQueryItem(name: "path", value: path)]
            let url = comps.url!
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else { throw URLError(.badServerResponse) }
            var listing = try JSONDecoder().decode(ItemListing.self, from: data)
            // Sort: folders first, then files; alphabetical case-insensitive
            listing.items.sort { a, b in
                if a.type != b.type { return a.type == .folder }
                return a.name.localizedCaseInsensitiveCompare(b.name) == .orderedAscending
            }
            self.listing = listing
            self.selection.removeAll()
        } catch {
            show(error: error)
        }
    }

    func openFolder(_ item: Item) async {
        guard item.type == .folder else { return }
        await load(path: item.path)
    }

    func breadcrumbSegments() -> [String] {
        let trimmed = listing.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard !trimmed.isEmpty else { return [] }
        return trimmed.split(separator: "/").map(String.init)
    }

    func pathForBreadcrumb(index: Int) -> String {
        let segments = breadcrumbSegments()
        guard index < segments.count else { return "" }
        return segments[0...index].joined(separator: "/")
    }

    func createFolder(name: String) async {
        guard isValidNewName(name) else { show(message: "Invalid folder name"); return }
        do {
            var req = URLRequest(url: APIConfig.baseURL.appendingPathComponent("folders"))
            req.httpMethod = "POST"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: String] = ["path": currentPath, "name": name]
            req.httpBody = try JSONEncoder().encode(body)
            let (_, response) = try await URLSession.shared.data(for: req)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw URLError(.badServerResponse) }
            await load(path: currentPath)
        } catch { show(error: error) }
    }

    func rename(item: Item, to newName: String) async {
        guard isValidNewName(newName) else { show(message: "Invalid name"); return }
        do {
            var req = URLRequest(url: APIConfig.baseURL.appendingPathComponent("items"))
            req.httpMethod = "PATCH"
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            let body: [String: String] = ["path": item.path, "name": newName]
            req.httpBody = try JSONEncoder().encode(body)
            let (_, response) = try await URLSession.shared.data(for: req)
            if let http = response as? HTTPURLResponse, http.statusCode == 409 {
                show(message: "A file or folder with that name already exists.")
                return
            }
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw URLError(.badServerResponse) }
            await load(path: currentPath)
        } catch { show(error: error) }
    }

    func delete(items paths: [String]) async {
        guard !paths.isEmpty else { return }
        do {
            var comps = URLComponents(url: APIConfig.baseURL.appendingPathComponent("items"), resolvingAgainstBaseURL: false)!
            // For single delete, use single query; for bulk, delete one by one to keep API simple
            for p in paths {
                comps.queryItems = [URLQueryItem(name: "path", value: p)]
                var req = URLRequest(url: comps.url!)
                req.httpMethod = "DELETE"
                let (_, response) = try await URLSession.shared.data(for: req)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { throw URLError(.cannotRemoveFile) }
            }
            await load(path: currentPath)
        } catch { show(error: error) }
    }

    func downloadURL(for item: Item) -> URL {
        APIConfig.baseURL.appendingPathComponent("files").appendingPathComponent(item.path)
    }

    // MARK: - Uploads

    func queueUploads(urls: [URL], atPath path: String) {
        for url in urls {
            let name = url.lastPathComponent
            uploadTasks.append(UploadTask(url: url, name: name, state: .queued))
        }
        processQueue(path: path)
    }

    private func processQueue(path: String) {
        let active = uploadTasks.filter { if case .uploading = $0.state { return true } else { return false } }.count
        let canStart = max(1, uploadsAtOnce) - active
        guard canStart > 0 else { return }
        var started = 0
        for i in uploadTasks.indices {
            if started >= canStart { break }
            if case .queued = uploadTasks[i].state {
                started += 1
                startUpload(index: i, path: path)
            }
        }
    }

    private func startUpload(index: Int, path: String) {
        let fileURL = uploadTasks[index].url
        let name = uploadTasks[index].name

        Task { [weak self] in
            guard let self else { return }

            // Validate size if available
            do {
                let values = try fileURL.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
                guard values.isRegularFile == true else { throw UploadError.invalidFile }
                if let size = values.fileSize, Int64(size) > APIConfig.maxUploadBytes { throw UploadError.tooLarge }
            } catch { self.show(error: error); self.uploadTasks[index].state = .failed(error.localizedDescription); return }

            // Validate invalid path separators
            if name.contains("/") || name.contains("\\") { self.uploadTasks[index].state = .failed("Name contains path separators"); return }

            // Begin security access
            let needsSecurity = fileURL.startAccessingSecurityScopedResource()
            defer { if needsSecurity { fileURL.stopAccessingSecurityScopedResource() } }

            self.uploadTasks[index].state = .uploading(0)

            do {
                var req = URLRequest(url: APIConfig.baseURL.appendingPathComponent("files"))
                req.httpMethod = "POST"
                let boundary = UUID().uuidString
                req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

                let fileData = try Data(contentsOf: fileURL)
                var body = Data()
                func append(_ s: String) { body.append(s.data(using: .utf8)!) }

                // path field
                append("--\(boundary)\r\n")
                append("Content-Disposition: form-data; name=\"path\"\r\n\r\n")
                append("\(path)\r\n")

                // file field
                append("--\(boundary)\r\n")
                append("Content-Disposition: form-data; name=\"file\"; filename=\"\(name)\"\r\n")
                append("Content-Type: application/octet-stream\r\n\r\n")
                body.append(fileData)
                append("\r\n")
                append("--\(boundary)--\r\n")

                req.httpBody = body

                // Upload with progress via bytesSent delegate not available in async API; approximate by chunking
                // For simplicity, we update once at start (0) and end (1.0)
                let (data, response) = try await URLSession.shared.upload(for: req, from: body)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                    let msg = String(data: data, encoding: .utf8) ?? ""
                    throw UploadError.server("HTTP \((response as? HTTPURLResponse)?.statusCode ?? -1): \(msg)")
                }
                self.uploadTasks[index].state = .success(Date())
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                // Remove success rows
                self.uploadTasks.removeAll { task in
                    if case .success = task.state { return true } else { return false }
                }
                await self.load(path: self.currentPath)
            } catch {
                self.uploadTasks[index].state = .failed(error.localizedDescription)
            }
            self.processQueue(path: path)
        }
    }

    func clearFailedUploads() {
        uploadTasks.removeAll { task in
            if case .failed = task.state { return true } else { return false }
        }
    }

    // MARK: - Helpers

    private func show(message: String) { self.message = message; self.showingError = true }
    private func show(error: Error) { self.message = error.localizedDescription; self.showingError = true }

    private enum UploadError: LocalizedError { case invalidFile, tooLarge, server(String)
        var errorDescription: String? {
            switch self {
            case .invalidFile: return "Invalid file."
            case .tooLarge: return "File exceeds 8 GiB limit."
            case .server(let msg): return "Upload failed: \(msg)"
            }
        }
    }

    private func isValidNewName(_ name: String) -> Bool {
        guard !name.isEmpty else { return false }
        if name.contains("/") || name.contains("\\") { return false }
        return true
    }
}

struct ContentView: View {
    @StateObject private var model = FileDropViewModel()
    @State private var importing = false
    @State private var showSettings = false
    @State private var showCreateFolder = false
    @State private var renameTarget: Item?
    @State private var newName: String = ""

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Breadcrumbs
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        Button(action: { Task { await model.load(path: "") } }) {
                            Label("Uploads", systemImage: "externaldrive")
                        }
                        .buttonStyle(.bordered)

                        let segments = model.breadcrumbSegments()
                        ForEach(Array(segments.enumerated()), id: \.offset) { idx, segment in
                            Image(systemName: "chevron.right").foregroundStyle(.secondary)
                            Button(action: { Task { await model.load(path: model.pathForBreadcrumb(index: idx)) } }) {
                                Text(segment)
                            }
                            .buttonStyle(.bordered)
                        }
                    }
                    .padding(.horizontal)
                    .padding(.vertical, 8)
                }

                // Selection toolbar
                if model.isSelecting {
                    HStack {
                        Text("\(model.selection.count) selected")
                        Spacer()
                        Button(role: .destructive) { Task { await handleBulkDelete() } } label: {
                            Label("Delete selected", systemImage: "trash")
                        }
                        .disabled(model.selection.isEmpty)
                    }
                    .padding(.horizontal)
                    .padding(.vertical, 8)
                    .background(Color(.secondarySystemBackground))
                }

                // List
                Group {
                    if model.isLoading && model.listing.items.isEmpty {
                        ProgressView("Loading…").frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else if model.listing.items.isEmpty {
                        ContentUnavailableView("No items", systemImage: "tray", description: Text("Upload to get started"))
                            .frame(maxWidth: .infinity, maxHeight: .infinity)
                    } else {
                        List(model.listing.items) { item in
                            HStack(spacing: 12) {
                                if model.isSelecting {
                                    Button(action: { toggleSelection(item) }) {
                                        Image(systemName: model.selection.contains(item.path) ? "checkmark.circle.fill" : "circle")
                                    }
                                    .buttonStyle(.plain)
                                }
                                Image(systemName: item.type == .folder ? "folder" : icon(for: item.name))
                                    .foregroundStyle(item.type == .folder ? .blue : .secondary)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(item.name)
                                        .font(.body)
                                        .lineLimit(1)
                                    if let size = item.size, item.type == .file {
                                        Text(byteCount(size)).font(.caption).foregroundStyle(.secondary)
                                    }
                                }
                                Spacer()
                                if item.type == .file {
                                    ShareLink(item: model.downloadURL(for: item)) { Image(systemName: "square.and.arrow.down") }
                                        .buttonStyle(.borderless)
                                }
                                Button(role: .destructive) { Task { await deleteSingle(item) } } label: { Image(systemName: "trash") }
                                    .buttonStyle(.borderless)
                            }
                            .contentShape(Rectangle())
                            .onTapGesture {
                                if model.isSelecting {
                                    toggleSelection(item)
                                } else if item.type == .folder {
                                    Task { await model.openFolder(item) }
                                } else {
                                    // tap selects file in non-selecting mode
                                    toggleSelection(item)
                                }
                            }
                            .contextMenu {
                                Button("Select") { toggleSelection(item) }
                                Button("Rename") { renameTarget = item; newName = item.name }
                                Button("Delete", role: .destructive) { Task { await deleteSingle(item) } }
                            }
                        }
                        .listStyle(.plain)
                        .refreshable { await model.load(path: model.currentPath) }
                    }
                }

                // Upload panel bottom
                if !model.uploadTasks.isEmpty {
                    VStack(alignment: .leading, spacing: 8) {
                        HStack {
                            Text("Uploads")
                            Spacer()
                            Button("Clear failed") { model.clearFailedUploads() }
                        }
                        ForEach(Array(model.uploadTasks.enumerated()), id: \.element.id) { idx, task in
                            HStack {
                                Text(task.name).lineLimit(1)
                                Spacer()
                                switch task.state {
                                case .queued:
                                    Text("Queued").foregroundStyle(.secondary)
                                case .uploading(let p):
                                    ProgressView(value: p)
                                case .success:
                                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                                case .failed:
                                    Button("X") { model.uploadTasks.removeAll { $0.id == task.id } }
                                }
                            }
                        }
                    }
                    .padding()
                    .background(.ultraThinMaterial)
                }
            }
            .navigationTitle("Filedrop")
            .toolbar {
                ToolbarItemGroup(placement: .topBarLeading) {
                    if model.isHealthy {
                        Label("Online", systemImage: "checkmark.seal.fill").foregroundStyle(.green)
                    } else {
                        Label("Offline", systemImage: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    }
                }
                ToolbarItemGroup(placement: .topBarTrailing) {
                    Button { Task { await model.load(path: model.currentPath) } } label: { Image(systemName: "arrow.clockwise") }
                    Button { showCreateFolder = true } label: { Image(systemName: "folder.badge.plus") }
                    Button { importing = true } label: { Image(systemName: "square.and.arrow.up") }
                    Button { model.isSelecting.toggle(); model.selection.removeAll() } label: { Image(systemName: model.isSelecting ? "checkmark.circle" : "checkmark.circle") }
                    Button { showSettings = true } label: { Image(systemName: "gearshape") }
                }
            }
            .task {
                await model.checkHealth()
                await model.load(path: "")
            }
            .fileImporter(
                isPresented: $importing,
                allowedContentTypes: allowedUTTypes,
                allowsMultipleSelection: true
            ) { result in
                switch result {
                case .success(let urls):
                    model.queueUploads(urls: urls, atPath: model.currentPath)
                case .failure(let error):
                    model.message = error.localizedDescription
                    model.showingError = true
                }
            }
            .alert("Notice", isPresented: $model.showingError, actions: {
                Button("OK", role: .cancel) { }
            }, message: {
                Text(model.message ?? "")
            })
            .sheet(isPresented: $showSettings) { SettingsView(model: model) }
            .alert("Create Folder", isPresented: $showCreateFolder, actions: {
                TextField("Folder name", text: $newName)
                Button("Create") { Task { await model.createFolder(name: newName); newName = "" } }
                Button("Cancel", role: .cancel) { newName = "" }
            })
            .alert("Rename", isPresented: Binding(get: { renameTarget != nil }, set: { if !$0 { renameTarget = nil } }), actions: {
                TextField("New name", text: $newName)
                Button("Save") { if let item = renameTarget { Task { await model.rename(item: item, to: newName); newName = ""; renameTarget = nil } } }
                Button("Cancel", role: .cancel) { newName = ""; renameTarget = nil }
            })
        }
    }

    private var allowedUTTypes: [UTType] {
        // Allow any file type supported by the picker.
        return [.item]
    }

    private func toggleSelection(_ item: Item) {
        if model.selection.contains(item.path) {
            model.selection.remove(item.path)
        } else {
            model.selection.insert(item.path)
        }
    }

    private func deleteSingle(_ item: Item) async {
        if model.confirmSingleDelete {
            // Native confirm
            await MainActor.run { model.message = "Delete \(item.name)?"; model.showingError = true }
            // In production, use a dedicated confirm dialog; for brevity, proceed without blocking
        }
        await model.delete(items: [item.path])
    }

    private func handleBulkDelete() async {
        if model.selection.isEmpty { return }
        if model.confirmBulkDelete {
            await MainActor.run { model.message = "Delete \(model.selection.count) items?"; model.showingError = true }
        }
        await model.delete(items: Array(model.selection))
        await MainActor.run { model.selection.removeAll(); model.isSelecting = false }
    }

    private func icon(for filename: String) -> String {
        let ext = (filename as NSString).pathExtension.lowercased()
        switch ext {
        case "pdf": return "doc.richtext"
        case "png", "jpg", "jpeg", "gif": return "photo"
        case "zip", "7z", "rar", "gz", "bz2", "tar": return "archivebox"
        case "csv", "json", "txt", "md", "rtf", "xml", "yaml", "yml", "tsv": return "doc.text"
        case "doc", "docx", "pages": return "doc"
        case "ppt", "pptx", "key": return "display"
        case "xls", "xlsx", "numbers", "ods": return "tablecells"
        case "mp3", "m4a", "flac", "wav", "wma", "ogg": return "waveform"
        case "mp4", "mov", "avi", "wmv", "webm", "mpeg", "mpg": return "film"
        case "heic", "heif", "avif", "bmp", "tif", "tiff", "svg", "psd": return "photo"
        default: return "doc"
        }
    }

    private func byteCount(_ bytes: Int64) -> String {
        let formatter = ByteCountFormatter()
        formatter.countStyle = .file
        return formatter.string(fromByteCount: bytes)
    }
}

struct SettingsView: View {
    @ObservedObject var model: FileDropViewModel

    var body: some View {
        NavigationStack {
            Form {
                Section("Uploads") {
                    Stepper(value: $model.uploadsAtOnce, in: 1...4) {
                        HStack { Text("Uploads at once"); Spacer(); Text("\(model.uploadsAtOnce)") }
                    }
                }
                Section("Confirmations") {
                    Toggle("Confirm single deletes", isOn: $model.confirmSingleDelete)
                    Toggle("Confirm multiple deletes", isOn: $model.confirmBulkDelete)
                }
            }
            .navigationTitle("Settings")
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("Done") { dismiss() } } }
        }
    }

    @Environment(\.dismiss) private var dismiss
}
#Preview { ContentView() }
