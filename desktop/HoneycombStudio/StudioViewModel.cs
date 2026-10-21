using CommunityToolkit.Mvvm.ComponentModel;
using System.Collections.ObjectModel;
using System.Text.Json.Nodes;

namespace HoneycombStudio;

public sealed record EvidenceRow(string Label, string Value, string Unit, string Source);

public partial class StudioViewModel : ObservableObject
{
    public ObservableCollection<BatchRow> Batches { get; } = [];
    public ObservableCollection<RunRow> Runs { get; } = [];
    [ObservableProperty] public partial string ConnectionState { get; set; } = "Đang kết nối";
    [ObservableProperty] public partial string? SelectedBatchId { get; set; }
    [ObservableProperty] public partial string? SelectedRunId { get; set; }

    public void UpdateBatches(IEnumerable<BatchRow> rows)
    {
        Reconcile(Batches, rows);
        if (SelectedBatchId is null)
            SelectedBatchId = (Batches.FirstOrDefault(row => row.Status == "running") ?? Batches.FirstOrDefault())?.Id;
    }
    public void UpdateRuns(IEnumerable<RunRow> rows)
    {
        Reconcile(Runs, rows);
        if (SelectedRunId is null)
            SelectedRunId = (Runs.FirstOrDefault(row => row.Status is not ("completed" or "review" or "failed" or "queued"))
                ?? Runs.FirstOrDefault())?.Id;
    }

    private static void Reconcile<T>(ObservableCollection<T> target, IEnumerable<T> rows) where T : DocumentRow
    {
        var desired = rows.ToList();
        var ids = desired.Select(row => row.Id).ToHashSet();
        for (int i = target.Count - 1; i >= 0; i--)
            if (!ids.Contains(target[i].Id)) target.RemoveAt(i);
        for (int i = 0; i < desired.Count; i++)
        {
            var existing = target.FirstOrDefault(row => row.Id == desired[i].Id);
            if (existing is null) target.Insert(i, desired[i]);
            else
            {
                existing.UpdateFrom(desired[i]);
                int oldIndex = target.IndexOf(existing);
                if (oldIndex != i) target.Move(oldIndex, i);
            }
        }
    }
}

public abstract class DocumentRow(JsonObject document) : ObservableObject
{
    public JsonObject Document { get; private set; } = document;
    public string Id => Document["id"]!.GetValue<string>();
    protected abstract Dictionary<string, object?> DisplayValues();
    public void UpdateFrom(DocumentRow other)
    {
        var before = DisplayValues();
        Document = other.Document;
        foreach (var (name, value) in DisplayValues())
            if (!Equals(before.GetValueOrDefault(name), value)) OnPropertyChanged(name);
    }
}

public sealed class BatchRow(JsonObject document) : DocumentRow(document)
{
    public string Name => Document["name"]!.GetValue<string>();
    public string Status => Document["status"]!.GetValue<string>();
    public string Counts => Document["counts"]?.ToJsonString() ?? $"{Document["runs_total"]} lượt";
    public string Percent => $"{Document["completed_percent"]?.GetValue<double>() ?? 0:0.#}%";
    protected override Dictionary<string, object?> DisplayValues() => new()
    {
        [nameof(Name)] = Name, [nameof(Status)] = Status, [nameof(Counts)] = Counts, [nameof(Percent)] = Percent
    };
}

public sealed class RunRow(JsonObject document) : DocumentRow(document)
{
    public string Index => Document["index"]?.ToString() ?? "";
    public string Status => Document["status"]!.GetValue<string>();
    public string Phase => Document["phase"]?.GetValue<string>() ?? "";
    private string ProgressKey => Phase switch { "extracting" => "extraction_percent", "analyzing" or "verifying_export" or "cataloguing" => "analysis_percent", "completed" => "solver_percent", "solving" => "solver_percent", _ => "phase_percent" };
    public double Progress => Document["progress"]?[ProgressKey]?.GetValue<double>() ?? 0;
    public bool Indeterminate => Status is "building" or "checking" or "rendering" or "reporting" or "recovering";
    public string Attempts => (Document["attempts"]?.AsArray().Count ?? 0).ToString();
    public double Energy => Document["resolved"]?["energy_J"]?.GetValue<double>() ?? 0;
    public string Loading => $"{Energy:0.###} / {Document["resolved"]?["velocity_m_s"]?.GetValue<double>():0.###}";
    public bool Eligible => Status == "completed" && (Document["quality"]?["ml_eligible"]?.GetValue<bool>() ?? false);
    public string Timing
    {
        get
        {
            var p = Document["progress"];
            var simulation = p?["simulation_time_s"]?.GetValue<double>();
            var etaKey = Phase switch { "extracting" => "eta_extraction_seconds", "analyzing" or "verifying_export" or "cataloguing" => "eta_analysis_seconds", "solving" => "eta_solver_seconds", _ => "eta_phase_seconds" };
            var eta = p?[etaKey]?.GetValue<double>();
            var attempts = Document["attempts"]?.AsArray();
            string elapsed = "—";
            if (attempts?.LastOrDefault() is JsonObject a && DateTimeOffset.TryParse(a["started_at"]?.ToString(), out var start))
            {
                var end = DateTimeOffset.TryParse(a["ended_at"]?.ToString(), out var finish) ? finish : DateTimeOffset.UtcNow;
                elapsed = (end - start).ToString(@"hh\:mm\:ss");
            }
            string cpu = p?["process_cpu_percent_of_machine"]?.GetValue<double>().ToString("0.#") ?? "—";
            double? ram = p?["process_ram_bytes"]?.GetValue<double>() / 1e9;
            string physical = simulation is null ? "— ms" : $"{simulation * 1000:0.###} ms";
            return $"{Progress:0.#}% {Phase} · {physical} · {elapsed} · ETA {(eta is null ? "—" : TimeSpan.FromSeconds(eta.Value).ToString(@"hh\:mm\:ss"))} · CPU {cpu}% · RAM {ram:0.00} GB";
        }
    }
    public string LibraryDescription => $"{Loading} · {Status} · ML: {(Eligible ? "đủ chất lượng số" : "chưa đủ")} · thay đổi: {Document["changes"]?.ToJsonString()}";
    protected override Dictionary<string, object?> DisplayValues() => new()
    {
        [nameof(Index)] = Index, [nameof(Status)] = Status, [nameof(Phase)] = Phase,
        [nameof(Progress)] = Progress, [nameof(Indeterminate)] = Indeterminate,
        [nameof(Attempts)] = Attempts, [nameof(Loading)] = Loading, [nameof(Energy)] = Energy,
        [nameof(Timing)] = Timing, [nameof(Eligible)] = Eligible, [nameof(LibraryDescription)] = LibraryDescription
    };
}
