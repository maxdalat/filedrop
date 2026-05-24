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
    static let maxUploadBytes: Int64 = 16 * 1024 * 1024 // 16 MB
    static let allowedExtensions: Set<String> = ["csv", "gif", "jpeg", "jpg", "json", "md", "pdf", "png", "txt", "zip"]
}

struct RemoteFile: Identifiable, Hashable, Codable {
    let id = UUID()
    let name: String

    enum CodingKeys: String, CodingKey { case name }
}

@MainActor
final class FileDropViewModel: ObservableObject {
    @Published var isHealthy: Bool = false
    @Published var files: [RemoteFile] = []
    @Published var isLoading: Bool = false
    @Published var message: String?
    @Published var showingError: Bool = false

    func checkHealth() async {
        do {
            let url = APIConfig.baseURL.appendingPathComponent("health")
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                throw URLError(.badServerResponse)
            }
            if let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let status = json["status"] as? String {
                isHealthy = (status == "ok")
            } else {
                isHealthy = false
            }
        } catch {
            isHealthy = false
            show(error: error)
        }
    }

    func refreshFiles() async {
        isLoading = true
        defer { isLoading = false }
        do {
            let url = APIConfig.baseURL.appendingPathComponent("files")
            let (data, response) = try await URLSession.shared.data(from: url)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200 else {
                throw URLError(.badServerResponse)
            }
            // Expecting an array of filenames; adapt if API returns objects
            if let names = try JSONSerialization.jsonObject(with: data) as? [String] {
                self.files = names.map { RemoteFile(name: $0) }
            } else {
                // Try decoding as array of objects { name: "..." }
                let decoded = try JSONDecoder().decode([RemoteFile].self, from: data)
                self.files = decoded
            }
        } catch {
            show(error: error)
        }
    }

    func uploadFile(url fileURL: URL) async {
        // Validate size
        do {
            let resourceValues = try fileURL.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])
            guard resourceValues.isRegularFile == true else { throw UploadError.invalidFile }
            if let size = resourceValues.fileSize, Int64(size) > APIConfig.maxUploadBytes {
                throw UploadError.tooLarge
            }
        } catch {
            show(error: error)
            return
        }

        // Validate extension and filename characters
        let name = fileURL.lastPathComponent
        guard Self.isValidFilename(name) else {
            show(message: "Invalid filename. Use letters, numbers, ., _, - only.")
            return
        }
        let ext = fileURL.pathExtension.lowercased()
        guard APIConfig.allowedExtensions.contains(ext) else {
            show(message: "Unsupported file type .\(ext)")
            return
        }

        isLoading = true
        defer { isLoading = false }

        do {
            var request = URLRequest(url: APIConfig.baseURL.appendingPathComponent("files"))
            request.httpMethod = "POST"

            let boundary = UUID().uuidString
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")

            // Build multipart body
            let fileData = try Data(contentsOf: fileURL)
            var body = Data()
            func append(_ string: String) { body.append(string.data(using: .utf8)!) }

            append("--\(boundary)\r\n")
            append("Content-Disposition: form-data; name=\"file\"; filename=\"\(name)\"\r\n")
            append("Content-Type: application/octet-stream\r\n\r\n")
            body.append(fileData)
            append("\r\n")
            append("--\(boundary)--\r\n")

            request.httpBody = body

            let (data, response) = try await URLSession.shared.upload(for: request, from: body)
            guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else {
                let serverMsg = String(data: data, encoding: .utf8) ?? ""
                throw UploadError.server("HTTP \((response as? HTTPURLResponse)?.statusCode ?? -1): \(serverMsg)")
            }
            await refreshFiles()
            show(message: "Uploaded \(name)")
        } catch {
            show(error: error)
        }
    }

    func downloadURL(for filename: String) -> URL {
        APIConfig.baseURL.appendingPathComponent("files").appendingPathComponent(filename)
    }

    private func show(message: String) {
        self.message = message
        self.showingError = true
    }

    private func show(error: Error) {
        self.message = error.localizedDescription
        self.showingError = true
    }

    private enum UploadError: LocalizedError {
        case invalidFile
        case tooLarge
        case server(String)

        var errorDescription: String? {
            switch self {
            case .invalidFile: return "Invalid file."
            case .tooLarge: return "File exceeds 16 MB limit."
            case .server(let msg): return "Upload failed: \(msg)"
            }
        }
    }

    private static func isValidFilename(_ name: String) -> Bool {
        // Letters, numbers, dots, underscores, and hyphens only
        let pattern = "^[A-Za-z0-9._-]+$"
        return name.range(of: pattern, options: .regularExpression) != nil
    }
}

struct ContentView: View {
    @StateObject private var model = FileDropViewModel()
    @State private var importing = false
    @State private var selectedFileURL: URL?

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.files.isEmpty {
                    ProgressView("Loading…")
                } else if model.files.isEmpty {
                    ContentUnavailableView("No files", systemImage: "tray", description: Text("Upload a file to get started"))
                } else {
                    List(model.files) { item in
                        HStack {
                            Image(systemName: icon(for: item.name))
                                .foregroundStyle(.secondary)
                            Text(item.name)
                                .lineLimit(1)
                            Spacer()
                            // Use ShareLink to allow saving/downloading
                            ShareLink(item: model.downloadURL(for: item.name)) {
                                Image(systemName: "square.and.arrow.down")
                            }
                            .buttonStyle(.borderless)
                            .help("Download")
                        }
                    }
                    .refreshable { await model.refreshFiles() }
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
                    Button {
                        Task { await model.refreshFiles() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    Button {
                        importing = true
                    } label: {
                        Image(systemName: "square.and.arrow.up")
                    }
                    .accessibilityLabel("Upload")
                }
            }
            .task {
                await model.checkHealth()
                await model.refreshFiles()
            }
            .fileImporter(
                isPresented: $importing,
                allowedContentTypes: allowedUTTypes,
                allowsMultipleSelection: true
            ) { result in
                switch result {
                case .success(let urls):
                    Task {
                        for url in urls {
                            await model.uploadFile(url: url)
                        }
                    }
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
        }
    }

    private var allowedUTTypes: [UTType] {
        var types: [UTType] = []
        for ext in APIConfig.allowedExtensions {
            if let type = UTType(filenameExtension: ext) {
                types.append(type)
            }
        }
        // Fallback to data if none resolved
        return types.isEmpty ? [.data] : types
    }

    private func icon(for filename: String) -> String {
        let ext = (filename as NSString).pathExtension.lowercased()
        switch ext {
        case "pdf": return "doc.richtext"
        case "png", "jpg", "jpeg", "gif": return "photo"
        case "zip": return "archivebox"
        case "csv", "json", "txt", "md": return "doc.text"
        default: return "doc"
        }
    }
}

#Preview {
    ContentView()
}
