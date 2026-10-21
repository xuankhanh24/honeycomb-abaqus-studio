using System.Diagnostics;
using System.Net.Http;
using System.Text;
using System.Text.Json.Nodes;

namespace HoneycombStudio;

public sealed class EngineClient
{
    private HttpClient? http;
    private readonly bool discoverSession;
    private readonly string sessionFile;
    private string? sessionIdentity;
    public EngineClient(HttpClient? transport = null, string? sessionPath = null)
    {
        http = transport;
        discoverSession = transport is null;
        sessionFile = sessionPath ?? Path.Combine(ConfigDirectory, "session.json");
    }
    public static string ConfigDirectory => Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "HoneycombStudio");
    public static string SettingsPath => Path.Combine(ConfigDirectory, "engine-settings.json");
    public string? RepositoryRoot { get; private set; }

    public static JsonObject ReadSettings()
    {
        if (File.Exists(SettingsPath)) return JsonNode.Parse(File.ReadAllText(SettingsPath))!.AsObject();
        return new JsonObject { ["data_root"] = "C:/UET/DO_AN/honeycomb-data", ["abaqus"] = "C:/SIMULIA/Commands/abaqus.bat" };
    }

    public async Task ConnectAsync()
    {
        Directory.CreateDirectory(ConfigDirectory);
        var session = sessionFile;
        if (await TrySession(session)) return;
        if (await StartRegisteredEngine())
        {
            for (int i = 0; i < 160; i++) { await Task.Delay(250); if (await TrySession(session)) return; }
            throw new InvalidOperationException("Windows đang khởi động engine độc lập. Xem logs/engine.log trong thư mục cấu hình HoneycombStudio.");
        }
        var settings = ReadSettings();
        var packaged = Path.Combine(AppContext.BaseDirectory, "runtime", "python.exe");
        string executable;
        string workDir;
        if (File.Exists(packaged)) { executable = packaged; workDir = AppContext.BaseDirectory; }
        else
        {
            var directory = new DirectoryInfo(AppContext.BaseDirectory);
            while (directory is not null && !File.Exists(Path.Combine(directory.FullName, "pyproject.toml"))) directory = directory.Parent;
            RepositoryRoot = directory?.FullName;
            if (RepositoryRoot is null) throw new InvalidOperationException("Không tìm thấy engine. Dùng bản phát hành có runtime hoặc chạy scripts/setup.ps1.");
            executable = Path.Combine(RepositoryRoot, ".venv", "Scripts", "python.exe");
            if (!File.Exists(executable)) throw new InvalidOperationException("Chưa có Python engine. Chạy scripts/setup.ps1 trong repo.");
            workDir = RepositoryRoot;
        }
        var start = new ProcessStartInfo(executable) { WorkingDirectory = workDir, UseShellExecute = false, CreateNoWindow = true };
        foreach (var arg in new[] { "-X", "utf8", "-m", "honeycomb_studio.cli", "serve", "--data-root", settings["data_root"]!.ToString(), "--abaqus", settings["abaqus"]!.ToString() }) start.ArgumentList.Add(arg);
        Process.Start(start);
        for (int i = 0; i < 80; i++) { await Task.Delay(250); if (await TrySession(session)) return; }
        throw new InvalidOperationException("Engine chưa khởi động sau 20 giây. Xem đường dẫn Abaqus/data và chạy scripts/start-engine.ps1 để xem log.");
    }

    private static async Task<bool> StartRegisteredEngine()
    {
        foreach (var verb in new[] { "/Query", "/Run" })
        {
            var start = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "schtasks.exe"))
            {
                UseShellExecute = false, CreateNoWindow = true,
                RedirectStandardOutput = true, RedirectStandardError = true
            };
            foreach (var arg in new[] { verb, "/TN", "HoneycombStudio-Engine" }) start.ArgumentList.Add(arg);
            using var process = Process.Start(start)!;
            var output = process.StandardOutput.ReadToEndAsync();
            var error = process.StandardError.ReadToEndAsync();
            await process.WaitForExitAsync();
            await Task.WhenAll(output, error);
            if (process.ExitCode != 0) return false;
        }
        return true;
    }

    private async Task<bool> TrySession(string file)
    {
        if (!File.Exists(file)) return false;
        try
        {
            var session = JsonNode.Parse(await File.ReadAllTextAsync(file))!;
            using var check = new HttpClient { Timeout = TimeSpan.FromSeconds(1) };
            var url = session["url"]!.GetValue<string>();
            var health = JsonNode.Parse(await check.GetStringAsync(url + "/health"));
            if (health?["service"]?.ToString() != "honeycomb-studio") return false;
            http?.Dispose();
            http = new HttpClient { BaseAddress = new Uri(url), Timeout = TimeSpan.FromMinutes(2) };
            http.DefaultRequestHeaders.Add("X-Honeycomb-Token", session["token"]!.GetValue<string>());
            sessionIdentity = url + "|" + session["token"]!.GetValue<string>();
            return true;
        }
        catch (Exception ex) when (ex is IOException or HttpRequestException or TaskCanceledException or System.Text.Json.JsonException) { return false; }
    }

    public async Task<JsonNode> Get(string path)
    {
        await RefreshSession();
        if (http is null) throw new InvalidOperationException("Engine chưa kết nối");
        try
        {
            using var response = await http.GetAsync(path);
            return await Read(response);
        }
        catch (HttpRequestException) when (discoverSession)
        {
            // GET is safe to replay; never replay a POST whose outcome is unknown.
            await ConnectAsync();
            using var response = await http!.GetAsync(path);
            return await Read(response);
        }
    }

    private async Task RefreshSession()
    {
        if (!discoverSession) return;
        var file = sessionFile;
        if (!File.Exists(file)) return;
        try
        {
            var session = JsonNode.Parse(await File.ReadAllTextAsync(file));
            var identity = session?["url"]?.ToString() + "|" + session?["token"]?.ToString();
            if (identity != sessionIdentity) await TrySession(file);
        }
        catch (Exception ex) when (ex is IOException or System.Text.Json.JsonException) { }
    }

    public async Task<JsonNode> Post(string path, JsonNode? data = null)
    {
        await RefreshSession();
        if (http is null) throw new InvalidOperationException("Engine chưa kết nối");
        using var content = new StringContent(data?.ToJsonString() ?? "{}", Encoding.UTF8, "application/json");
        using var response = await http.PostAsync(path, content);
        return await Read(response);
    }

    private static async Task<JsonNode> Read(HttpResponseMessage response)
    {
        var text = await response.Content.ReadAsStringAsync();
        if (!response.IsSuccessStatusCode) throw new InvalidOperationException(text);
        return JsonNode.Parse(text) ?? new JsonObject();
    }

    public async Task<JsonNode> WaitOperation(JsonNode op, Action<string> progress)
    {
        if (op["id"] is null || op["status"] is null) return op;
        string id = op["id"]!.ToString();
        while (op["status"]?.ToString() == "running")
        {
            progress("Đang xử lý " + op["kind"] + "; mô phỏng và giao diện vẫn hoạt động.");
            await Task.Delay(1000); op = await Get("/v1/operations/" + id);
        }
        if (op["status"]?.ToString() == "failed") throw new InvalidOperationException(op["error"]?.ToString());
        return op["result"] ?? op;
    }
}
