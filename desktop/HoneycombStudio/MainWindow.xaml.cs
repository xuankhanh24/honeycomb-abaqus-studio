using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Automation;
using System.Collections.ObjectModel;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace HoneycombStudio;

public sealed partial class MainWindow : Window
{
    public StudioViewModel ViewModel { get; } = new();
    private readonly EngineClient client = new();
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(2) };
    private JsonObject model = new();
    private JsonObject baseSpec = new();
    private JsonArray parameters = new();
    private readonly List<AxisEditor> axes = [];
    private List<BatchRow> batchRows = [];
    private List<RunRow> runRows = [];
    private JsonArray historyRows = new();
    private JsonArray paretoGroups = new();
    private bool connected, refreshing, updatingLists;
    private int eventCursor;
    private readonly Queue<string> recentEvents = new();
    private readonly JsonSerializerOptions pretty = new() { WriteIndented = true, Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping };

    public MainWindow()
    {
        InitializeComponent();
        AppWindow.Resize(new Windows.Graphics.SizeInt32(1550, 1050));
        JobList.ItemsSource = ViewModel.Batches;
        RunList.ItemsSource = ViewModel.Runs;
        timer.Tick += async (_, _) => await Guard(Refresh);
        Navigation.SelectedItem = Navigation.MenuItems[0];
        _ = Guard(Initialize);
    }

    private void Message(string message, bool error = false)
    {
        Banner.Title = error ? "Cần xử lý" : "Honeycomb Studio";
        Banner.Message = message.Length > 700 ? message[..700] + "… Xem log hoặc chi tiết lượt để đọc đầy đủ." : message;
        Banner.Severity = error ? InfoBarSeverity.Error : InfoBarSeverity.Informational;
        Banner.IsOpen = true;
    }
    private async Task Guard(Func<Task> action)
    {
        try { await action(); }
        catch (Exception ex) { Message(ex.Message, true); }
    }
    private async Task Initialize()
    {
        await client.ConnectAsync(); connected = true;
        var template = await client.Get("/v1/template");
        baseSpec = template["spec"]!.DeepClone().AsObject();
        model = baseSpec["model"]!.DeepClone().AsObject();
        parameters = template["parameters"]!.DeepClone().AsArray();
        BuildParameterForm();
        ModelJson.Text = model.ToJsonString(pretty);
        if (axes.Count == 0) AddAxisEditor("energy_J", .85, 13, 1);
        var settings = EngineClient.ReadSettings();
        DataRoot.Text = settings["data_root"]!.ToString(); AbaqusPath.Text = settings["abaqus"]!.ToString();
        ReferencePath.Text = "C:/UET/DO_AN/mo_phong/Honeycomb-paper-7J/Honeycomb-7J-run.odb";
        await Refresh(); timer.Start(); Message("Engine đã kết nối. Các giá trị mặc định theo mô hình tham chiếu; chưa xác nhận hội tụ.");
    }
    private async Task Refresh()
    {
        if (!connected || refreshing) return;
        refreshing = true;
        try
        {
            var status = await client.Get("/v1/status");
            ResourceText.Text = $"Dữ liệu: {status["data_root"]}\nAbaqus: {status["abaqus"]}\nRAM khả dụng: {status["ram_available_gb"]!.GetValue<double>():0.0} / {status["ram_total_gb"]!.GetValue<double>():0.0} GB · Ổ đĩa trống: {status["disk_free_gb"]!.GetValue<double>():0.0} GB · {status["batches"]} job / {status["runs"]} lượt";
            if (status["test_solver"]?.GetValue<bool>() == true) Message("TEST SOLVER — không phải kết quả mô phỏng vật lý", true);
            BackupStatus.Text = status["backup"]!.ToJsonString(pretty);
            var items = (await client.Get("/v1/batches")).AsArray();
            batchRows = items.Select(n => new BatchRow(n!.AsObject())).ToList();
            updatingLists = true;
            ApplyJobFilter();
            updatingLists = false;
            if (ViewModel.SelectedBatchId is not null)
            {
                var detail = await client.Get("/v1/batches/" + ViewModel.SelectedBatchId);
                if (detail["resource_error"] is not null) Message(detail["resource_error"]!.ToString(), true);
                runRows = detail["runs"]!.AsArray().Select(n => new RunRow(n!.AsObject())).ToList();
                var old = ViewModel.Runs.FirstOrDefault(r => r.Id == ViewModel.SelectedRunId)?.Status;
                ApplyRunSort();
                if (ViewModel.SelectedRunId is not null && runRows.FirstOrDefault(r => r.Id == ViewModel.SelectedRunId)?.Status != old) await LoadRunDetail();
            }
            var events = (await client.Get("/v1/events?after=" + eventCursor)).AsArray();
            foreach (var item in events)
            {
                eventCursor = item!["seq"]!.GetValue<int>();
                var payload = item["payload"]!;
                var message = payload["type"]?.ToString() switch
                {
                    "phase" => "Giai đoạn: " + payload["phase"], "control" => "Điều khiển job: " + payload["action"],
                    "batch_created" => "Tạo job với " + payload["runs"] + " lượt", "completed" => "Hoàn tất dữ liệu và báo cáo",
                    "error" or "worker_error" or "backup_error" => "Cần xử lý: " + payload["error"]?.ToString().Split('\n')[0],
                    _ => payload["type"]?.ToString() ?? "Sự kiện"
                };
                if (message.Length > 200) message = message[..200] + "…";
                recentEvents.Enqueue($"{DateTimeOffset.Parse(item["time"]!.ToString()).ToLocalTime():dd/MM HH:mm:ss} · {item["run_id"]?.ToString().Split('_').LastOrDefault()} · {message}");
                while (recentEvents.Count > 30) recentEvents.Dequeue();
            }
            ActivityText.Text = string.Join("\n", recentEvents.Reverse());
        }
        finally { updatingLists = false; refreshing = false; }
    }
    private void Navigate(NavigationView sender, NavigationViewSelectionChangedEventArgs args)
    {
        string page = (args.SelectedItem as NavigationViewItem)?.Tag?.ToString() ?? "overview";
        OverviewPanel.Visibility = page == "overview" ? Visibility.Visible : Visibility.Collapsed;
        CreatePanel.Visibility = page == "create" ? Visibility.Visible : Visibility.Collapsed;
        JobsPanel.Visibility = page == "jobs" ? Visibility.Visible : Visibility.Collapsed;
        LibraryPanel.Visibility = page == "library" ? Visibility.Visible : Visibility.Collapsed;
        SettingsPanel.Visibility = page == "settings" ? Visibility.Visible : Visibility.Collapsed;
        if (page == "library" && connected) _ = Guard(LoadLibrary);
    }
    private void NewStudy(object sender, RoutedEventArgs e) => Navigation.SelectedItem = Navigation.MenuItems[1];
    private async void RefreshClicked(object sender, RoutedEventArgs e) => await Guard(async () => { await Refresh(); if (ViewModel.SelectedRunId is not null) await LoadRunDetail(); });
    private async void Reconnect(object sender, RoutedEventArgs e) => await Guard(Initialize);

    private static string Group(string key) => key.StartsWith("face_material") ? "Vật liệu mặt" : key.StartsWith("core_material") ? "Vật liệu lõi" : key.Contains("seed") || key.Contains("divisions") || key is "mesh_preset" or "fine_radius" or "skin_patch_half" or "shell_points" or "shell_element" ? "Lưới" : key is "loading" or "energy_J" or "velocity_m_s" or "mass_kg" or "ball_diameter" or "impact_x" or "impact_y" or "gap" or "gravity" ? "Va đập" : key.Contains("contact") || key.Contains("bond") || key.Contains("friction") || key.Contains("tie") || key == "clamp_diameter" ? "Liên kết và điều kiện biên" : key.Contains("interval") || key.Contains("variables") || key is "duration" or "cpus" or "precision" or "mass_scaling" or "bulk_linear" or "bulk_quadratic" ? "Solver và output" : "Hình học";
    private JsonNode? Value(string key)
    {
        JsonNode? n = model; foreach (var part in key.Split('.')) n = n?[part]; return n;
    }
    private void SetValue(string key, JsonNode? value)
    {
        JsonObject node = model;
        var parts = key.Split('.'); foreach (var part in parts[..^1]) node = node[part]!.AsObject();
        node[parts[^1]] = value;
    }
    private void BuildParameterForm()
    {
        ParameterGroups.Children.Clear();
        foreach (var group in parameters.Select(p => p!.AsObject()).GroupBy(p => Group(p["key"]!.ToString())))
        {
            var stack = new StackPanel { Spacing = 10, Padding = new Thickness(4, 12, 4, 12) };
            foreach (var descriptor in group)
            {
                string key = descriptor["key"]!.ToString(); string unit = descriptor["unit"]?.ToString() ?? "";
                var row = new Grid { ColumnSpacing = 16 };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(310) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(240) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                var label = new TextBlock { Text = descriptor["title"] + (unit.Length > 0 ? " (" + unit + ")" : ""), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };
                ToolTipService.SetToolTip(label, key); row.Children.Add(label);
                var source = new TextBlock { Text = descriptor["source"]?.ToString(), FontSize = 12, Opacity = .8, TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center }; Grid.SetColumn(source, 2); row.Children.Add(source);
                var current = Value(key);
                FrameworkElement editor;
                var options = key switch
                {
                    "loading" => new[] { "energy", "velocity" }, "mesh_preset" => ["reference", "quick", "fine", "custom"],
                    "face_material.hardening" or "core_material.hardening" => ["shifted_ramberg_osgood", "perfect_plastic", "bilinear", "table"],
                    _ => Array.Empty<string>()
                };
                if (options.Length > 0)
                {
                    var combo = new ComboBox { ItemsSource = options, SelectedItem = current?.ToString(), HorizontalAlignment = HorizontalAlignment.Stretch };
                    combo.SelectionChanged += (_, _) =>
                    {
                        if (combo.SelectedItem is not string v) return;
                        SetValue(key, JsonValue.Create(v));
                        if (key == "loading") foreach (var axis in axes)
                        {
                            string? old = axis.Key.SelectedItem?.ToString();
                            if (old is not ("energy_J" or "velocity_m_s")) continue;
                            axis.Key.SelectedItem = v == "energy" ? "energy_J" : "velocity_m_s";
                            axis.Values.Text = "";
                            axis.Start.Value = v == "energy" ? .85 : Math.Sqrt(2 * .85 / model["mass_kg"]!.GetValue<double>());
                            axis.Stop.Value = v == "energy" ? 13 : Math.Sqrt(2 * 13 / model["mass_kg"]!.GetValue<double>());
                            axis.Step.Value = v == "energy" ? 1 : .2; axis.End.IsChecked = true;
                        }
                        if (key == "mesh_preset") DispatcherQueue.TryEnqueue(BuildParameterForm);
                    }; editor = combo;
                }
                else if (current is JsonArray)
                {
                    var button = new Button { Content = "Xem / sửa bảng JSON", HorizontalAlignment = HorizontalAlignment.Stretch };
                    button.Click += async (_, _) => await Guard(async () =>
                    {
                        var box = new TextBox { Text = Value(key)?.ToJsonString(pretty), AcceptsReturn = true, TextWrapping = TextWrapping.Wrap, MinHeight = 350, MinWidth = 500 };
                        var dialog = new ContentDialog { Title = key, Content = new ScrollViewer { Content = box }, PrimaryButtonText = "Áp dụng", CloseButtonText = "Đóng", XamlRoot = Navigation.XamlRoot };
                        if (await dialog.ShowAsync() == ContentDialogResult.Primary) SetValue(key, JsonNode.Parse(box.Text ?? "[]"));
                    }); editor = button;
                }
                else if (current is JsonValue v && v.TryGetValue<bool>(out var boolean))
                {
                    var check = new CheckBox { IsChecked = boolean, Content = key is "mass_scaling" or "perfect_bond" or "core_self_contact" ? "Cố định trong phiên bản đầu" : "Bật", IsEnabled = key is not ("mass_scaling" or "perfect_bond" or "core_self_contact") };
                    check.Checked += (_, _) => SetValue(key, JsonValue.Create(true)); check.Unchecked += (_, _) => SetValue(key, JsonValue.Create(false)); editor = check;
                }
                else if (current is null || current is JsonValue nv && nv.TryGetValue<double>(out _))
                {
                    var box = new NumberBox { Value = current?.GetValue<double>() ?? double.NaN, PlaceholderText = "Tự tính từ mặt trên", SpinButtonPlacementMode = NumberBoxSpinButtonPlacementMode.Compact };
                    if (descriptor["type"]?.ToString().Contains("Literal") == true || key == "impactor_poisson") box.IsEnabled = false;
                    if ((key.Contains("seed") || key == "core_z_divisions") && model["mesh_preset"]?.ToString() != "custom") { box.IsEnabled = false; source.Text += " · theo preset; chọn custom để sửa"; }
                    box.ValueChanged += (_, args) =>
                    {
                        if (double.IsFinite(args.NewValue)) SetValue(key, JsonValue.Create(args.NewValue));
                        else if (key == "bottom_skin") SetValue(key, null);
                    }; editor = box;
                }
                else
                {
                    var box = new TextBox { Text = current?.ToString() ?? "", IsReadOnly = key is "precision" or "shell_element" };
                    box.TextChanged += (_, _) => SetValue(key, JsonValue.Create(box.Text)); editor = box;
                }
                AutomationProperties.SetLabeledBy(editor, label);
                AutomationProperties.SetName(editor, label.Text);
                AutomationProperties.SetHelpText(editor, key + ". Nguồn: " + source.Text);
                Grid.SetColumn(editor, 1); row.Children.Add(editor); stack.Children.Add(row);
            }
            ParameterGroups.Children.Add(new Expander { Header = group.Key, Content = stack, IsExpanded = group.Key is "Hình học" or "Va đập", HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch });
        }
    }
    private sealed record AxisEditor(Grid Row, ComboBox Key, NumberBox Start, NumberBox Stop, NumberBox Step, CheckBox End, TextBox Values);
    private void AddAxisEditor(string key = "core_height", double start = 15, double stop = 25, double step = 5)
    {
        var panel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        var numericKeys = parameters.Select(p => p!.AsObject()).Where(p => p["sweep_allowed"]?.GetValue<bool>() != false && (p["type"]?.ToString().Contains("Literal") != true || p["key"]!.ToString().EndsWith(".hardening"))).Select(p => p["key"]!.ToString()).Where(k => Value(k) is JsonValue v && v.TryGetValue<double>(out _) || k == "bottom_skin" || k.EndsWith(".hardening")).ToArray();
        var combo = new ComboBox { Header = "Tham số", ItemsSource = numericKeys, SelectedItem = key, Width = 250 };
        var a = new NumberBox { Header = "Đầu", Value = start, Width = 105 };
        var b = new NumberBox { Header = "Cuối", Value = stop, Width = 105 };
        var h = new NumberBox { Header = "Bước", Value = step, Width = 105 };
        var end = new CheckBox { Content = "Thêm điểm cuối", VerticalAlignment = VerticalAlignment.Bottom };
        var vals = new TextBox { Header = "Hoặc danh sách (JSON)", PlaceholderText = "[0.85, 2, 7, 13]", Width = 230 };
        var remove = new Button { Content = "Bỏ", VerticalAlignment = VerticalAlignment.Bottom };
        foreach (var control in new FrameworkElement[] { combo, a, b, h, end, vals, remove }) panel.Children.Add(control);
        combo.SelectionChanged += (_, _) => { if (combo.SelectedItem?.ToString()?.EndsWith(".hardening") == true) vals.Text = "[\"perfect_plastic\",\"shifted_ramberg_osgood\",\"bilinear\"]"; };
        var row = new Grid(); row.Children.Add(new ScrollViewer { Content = panel, HorizontalScrollMode = ScrollMode.Enabled, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollMode = ScrollMode.Disabled }); var editor = new AxisEditor(row, combo, a, b, h, end, vals); axes.Add(editor); AxesPanel.Children.Add(row);
        remove.Click += (_, _) => { axes.Remove(editor); AxesPanel.Children.Remove(row); };
    }
    private void AddAxis(object sender, RoutedEventArgs e) => AddAxisEditor();
    private JsonObject Spec()
    {
        var spec = baseSpec.DeepClone().AsObject(); spec["name"] = BatchName.Text; spec["model"] = model.DeepClone();
        spec["sampling"] = ((ComboBoxItem)SamplingMode.SelectedItem).Tag!.ToString();
        spec["samples"] = (int)SampleCount.Value; spec["seed"] = (int)RandomSeed.Value;
        spec["project_id"] = ProjectName.Text; spec["notes"] = StudyNotes.Text;
        spec["runtime_budget_minutes"] = RuntimeBudget.Value; spec["min_free_gb"] = DiskReserve.Value;
        spec["min_available_ram_gb"] = RamReserve.Value; spec["max_runs"] = (int)MaxRuns.Value;
        spec["render_images"] = RenderImages.IsChecked == true; spec["backup_after_run"] = BackupAfterRun.IsChecked == true;
        var array = new JsonArray();
        foreach (var axis in axes)
        {
            var a = new JsonObject { ["parameter"] = axis.Key.SelectedItem?.ToString(), ["include_stop"] = axis.End.IsChecked == true };
            if (!string.IsNullOrWhiteSpace(axis.Values.Text)) a["values"] = JsonNode.Parse(axis.Values.Text);
            else { a["start"] = axis.Start.Value; a["stop"] = axis.Stop.Value; a["step"] = axis.Step.Value; }
            array.Add(a);
        }
        spec["axes"] = array; spec["designs"] = JsonNode.Parse(DesignsJson.Text); return spec;
    }
    private async Task Preview()
    {
        var preview = await client.Post("/v1/preview", Spec());
        var resolved = await client.Post("/v1/resolve", model.DeepClone());
        PreviewSummary.Text = $"{preview["count"]} lượt · Ước tính solver {preview["estimated_solver_minutes"]} phút · ODB gốc {preview["estimated_raw_odb_gb"]} GB, chưa gồm dữ liệu xuất và scratch.\n{preview["runtime_note"]}";
        PreviewJson.Text = new JsonObject { ["preview"] = preview.DeepClone(), ["input_thuc_te_mo_hinh_nen"] = resolved.DeepClone() }.ToJsonString(pretty);
        Message("Preview hợp lệ. Kiểm tra danh sách lượt và input thực tế trước khi tạo job.");
    }
    private async void PreviewStudy(object sender, RoutedEventArgs e) => await Guard(Preview);
    private async void CreateStudy(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        await Preview(); var batch = await client.Post("/v1/batches", Spec()); ViewModel.SelectedBatchId = batch["id"]!.ToString();
        Navigation.SelectedItem = Navigation.MenuItems[2]; await Refresh(); Message("Đã tạo job. Chọn Chạy / Tiếp tục để bắt đầu.");
    });
    private void LoadJsonFromForm(object sender, RoutedEventArgs e) => ModelJson.Text = model.ToJsonString(pretty);
    private async void ApplyModelJson(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var parsed = JsonNode.Parse(ModelJson.Text)!.AsObject(); await client.Post("/v1/resolve", parsed); model = parsed; BuildParameterForm(); Message("Đã áp dụng JSON và kiểm tra input.");
    });
    private async void ImportDesignCsv(object sender, RoutedEventArgs e) => await Guard(async () => { var data = await client.Post("/v1/import-designs", new JsonObject { ["path"] = DesignCsvPath.Text }); DesignsJson.Text = data["designs"]!.ToJsonString(pretty); SamplingMode.SelectedIndex = 2; });
    private void ApplyJobFilter()
    {
        ViewModel.Batches.Clear(); foreach (var b in batchRows.Where(b => b.Name.Contains(JobSearch.Text, StringComparison.OrdinalIgnoreCase))) ViewModel.Batches.Add(b);
        JobList.SelectedItem = ViewModel.Batches.FirstOrDefault(b => b.Id == ViewModel.SelectedBatchId);
    }
    private void FilterJobs(object sender, TextChangedEventArgs e) { if (!updatingLists) { updatingLists = true; ApplyJobFilter(); updatingLists = false; } }
    private async void SelectBatch(object sender, SelectionChangedEventArgs e)
    {
        if (updatingLists || JobList.SelectedItem is not BatchRow b) return;
        ViewModel.SelectedBatchId = b.Id; ViewModel.SelectedRunId = null; await Guard(Refresh);
    }
    private void ApplyRunSort()
    {
        updatingLists = true;
        IEnumerable<RunRow> ordered = RunSort.SelectedIndex switch { 1 => runRows.OrderBy(r => r.Energy), 2 => runRows.OrderBy(r => r.Status), _ => runRows.OrderBy(r => int.Parse(r.Index)) };
        string filter = (RunFilter?.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "";
        ViewModel.Runs.Clear(); foreach (var r in ordered.Where(r => filter.Length == 0 || r.Status == filter)) ViewModel.Runs.Add(r);
        RunList.SelectedItem = ViewModel.Runs.FirstOrDefault(r => r.Id == ViewModel.SelectedRunId); updatingLists = false;
    }
    private void SortRuns(object sender, SelectionChangedEventArgs e) { if (RunList is not null) ApplyRunSort(); }
    private async void SelectRun(object sender, SelectionChangedEventArgs e)
    {
        if (updatingLists || RunList.SelectedItem is not RunRow r) return;
        ViewModel.SelectedRunId = r.Id; await Guard(LoadRunDetail);
    }
    private async Task LoadRunDetail()
    {
        if (ViewModel.SelectedRunId is null) return;
        var run = await client.Get("/v1/runs/" + ViewModel.SelectedRunId);
          SelectedRunTitle.Text = (batchRows.FirstOrDefault(b => b.Id == run["batch_id"]?.ToString())?.Name ?? "Job") + " · Lượt " + run["index"] + " · " + run["id"];
          ToolTipService.SetToolTip(SelectedRunTitle,SelectedRunTitle.Text);
          var inputs = new List<EvidenceRow>();
          AddEvidence(run["resolved"],"",inputs,run["changes"]?.AsObject());
          if(run["attempts"]?.AsArray().LastOrDefault() is JsonObject latest)
          {
              string actualFile=Path.Combine(latest["path"]!.ToString(),"raw","model_manifest.json");
              if(File.Exists(actualFile) && JsonNode.Parse(await File.ReadAllTextAsync(actualFile)) is JsonObject actual)
              {
                  var measured=new JsonObject();
                  foreach(var property in actual) if(!JsonNode.DeepEquals(run["resolved"]?[property.Key],property.Value)) measured[property.Key]=property.Value?.DeepClone();
                  AddEvidence(measured,"measured.",inputs);
              }
          }
          RunInputs.ItemsSource=inputs;
          var outputs=new List<EvidenceRow>();
          AddEvidence(run["summary"],"output.",outputs);
          AddEvidence(run["quality"],"quality.",outputs);
          RunOutputs.ItemsSource=outputs.Count>0?outputs:[new("Kết quả","Chưa có output. Chạy lượt và chờ trích xuất hoàn tất.","","")];
          var attemptsEvidence=new List<EvidenceRow>();
          foreach(var item in run["attempts"]!.AsArray())
              if(item is JsonObject attempt) foreach(var key in new[]{"number","started_at","ended_at","process_phase","durations","error"})
                  AddEvidence(new JsonObject{[key]=attempt[key]?.DeepClone()},"attempt "+attempt["number"]+".",attemptsEvidence);
          RunAttempts.ItemsSource=attemptsEvidence.Count>0?attemptsEvidence:[new("Attempt","Lượt chưa được thực thi.","","")];
        RunDetailJson.Text = run.ToJsonString(pretty);
        RunLogs.Text = (await client.Get("/v1/runs/" + ViewModel.SelectedRunId + "/logs")).ToJsonString(pretty);
        historyRows = (await client.Get("/v1/runs/" + ViewModel.SelectedRunId + "/history")).AsArray(); PlotHistory();
        FigureGallery.Children.Clear();
        var attempts = run["attempts"]!.AsArray();
        if (attempts.LastOrDefault() is JsonObject a)
        {
            var root = Path.Combine(a["path"]!.ToString(), "figures");
            if (Directory.Exists(root)) foreach (var imageFile in Directory.GetFiles(root, "*.png").Order())
            {
                var image = new Microsoft.UI.Xaml.Controls.Image { Width = 350, MaxHeight = 260, Stretch = Stretch.Uniform };
                var bitmap = new BitmapImage { DecodePixelWidth = 700 };
                var file = await Windows.Storage.StorageFile.GetFileFromPathAsync(imageFile);
                using var stream = await file.OpenReadAsync(); await bitmap.SetSourceAsync(stream); image.Source = bitmap;
                var stack = new StackPanel { Spacing = 8 }; stack.Children.Add(new TextBlock { Text = Path.GetFileNameWithoutExtension(imageFile), TextWrapping = TextWrapping.Wrap, MaxWidth = 350 }); stack.Children.Add(image); FigureGallery.Children.Add(stack);
            }
        }
        if(FigureGallery.Children.Count==0) FigureGallery.Children.Add(new TextBlock{Text="Chưa có ảnh mô phỏng. Bật render ảnh khi tạo job và chờ bước hậu xử lý hoàn tất.",TextWrapping=TextWrapping.Wrap,MaxWidth=550,Margin=new Thickness(16)});
    }
    private void AddEvidence(JsonNode? node,string prefix,List<EvidenceRow> target,JsonObject? changes=null)
    {
        if(node is not JsonObject values) return;
        foreach(var entry in values)
        {
            string key=prefix+entry.Key;
            if(entry.Value is JsonObject nested){AddEvidence(nested,key+".",target,changes);continue;}
            var descriptor=parameters.FirstOrDefault(p=>p?["key"]?.ToString()==key);
            string label=descriptor?["title"]?.ToString()??key;
            string unit=descriptor?["unit"]?.ToString()??(key.EndsWith("_mm")?"mm":key.EndsWith("_N")?"N":key.EndsWith("_J")?"J":key.EndsWith("_kg")?"kg":key.EndsWith("_ms")?"ms":key.EndsWith("_s")?"s":key.EndsWith("percent")?"%":"");
            string state=changes?.ContainsKey(key)==true?"Khảo sát":descriptor is null?"Suy ra / kết quả":"Cố định";
            string source=state+" · "+(descriptor?["source"]?.ToString()??"Input thực tế / ODB; xem định nghĩa trong tài liệu dữ liệu");
            if(key.EndsWith("plastic_table") && entry.Value is JsonArray curve)
            {
                for(int i=0;i<curve.Count;i++) target.Add(new(key+" ["+i+"]",curve[i]?[0]+" / "+curve[i]?[1],"MPa / strain",source));
            }
            else target.Add(new(label,entry.Value is JsonArray?entry.Value.ToJsonString():entry.Value?.ToString()??"Chưa ghi / không áp dụng",unit,source));
        }
    }
    private void ChangeChart(object sender, SelectionChangedEventArgs e) { if (RunPlot is not null) PlotHistory(); }
    private void PlotHistory()
    {
        if (RunPlot is null) return; RunPlot.Plot.Clear(); if (historyRows.Count == 0) { RunPlot.Plot.Title("Chưa có đường cong. Chờ trích xuất kết quả của lượt."); RunPlot.Refresh(); return; }
        RunPlot.Plot.Title("Dữ liệu thô từ lượt đã chọn");
        double[] values(string key) => historyRows.Select(r => r?[key]?.GetValue<double>() ?? double.NaN).ToArray();
        if (ChartKind.SelectedIndex == 3)
        {
            foreach (var key in new[] { "ALLKE", "ALLIE", "ALLPD", "ALLSE", "ALLAE", "ALLVD", "ETOTAL" }) { var series = RunPlot.Plot.Add.Scatter(values("time_ms"), values(key + "_J")); series.LegendText = key; }
            RunPlot.Plot.XLabel("Thời gian (ms)"); RunPlot.Plot.YLabel("Năng lượng (J)"); RunPlot.Plot.ShowLegend();
        }
        else
        {
            bool forceDisp = ChartKind.SelectedIndex == 1, dispTime = ChartKind.SelectedIndex == 2;
            RunPlot.Plot.Add.Scatter(values(forceDisp ? "impactor_displacement_mm" : "time_ms"), values(dispTime ? "impactor_displacement_mm" : "contact_force_N"));
            RunPlot.Plot.XLabel(forceDisp ? "Chuyển vị viên (mm)" : "Thời gian (ms)"); RunPlot.Plot.YLabel(dispTime ? "Chuyển vị viên (mm)" : "Lực tiếp xúc (N)");
        }
        RunPlot.Plot.Axes.AutoScale(); RunPlot.Refresh();
    }
    private async Task BatchAction(string action)
    {
        if (ViewModel.SelectedBatchId is null) throw new InvalidOperationException("Chọn job trước");
        await client.Post($"/v1/batches/{ViewModel.SelectedBatchId}/{action}"); await Refresh();
    }
    private async void StartBatch(object sender, RoutedEventArgs e) => await Guard(() => BatchAction("resume"));
    private async void StopBatch(object sender, RoutedEventArgs e) => await Guard(() => BatchAction("stop"));
    private async void PauseAfterCurrent(object sender, RoutedEventArgs e) => await Guard(() => BatchAction("pause_after_current"));
    private bool detailExpanded;
    private void ExpandDetails(object sender, RoutedEventArgs e)
    {
        detailExpanded = !detailExpanded;
        JobList.Visibility = detailExpanded ? Visibility.Collapsed : Visibility.Visible;
        JobsPanel.RowDefinitions[1].Height = new GridLength(detailExpanded ? 0 : 110);
        JobsPanel.RowDefinitions[3].MinHeight = detailExpanded ? 0 : 110;
        JobsPanel.RowDefinitions[3].Height = detailExpanded ? new GridLength(0) : new GridLength(1, GridUnitType.Star);
        ((FrameworkElement)RunList.Parent).Visibility = detailExpanded ? Visibility.Collapsed : Visibility.Visible;
        ((Button)sender).Content = detailExpanded ? "Hiện bảng lượt" : "Mở rộng chi tiết";
    }
    private async Task OpenRun(string kind)
    {
        if (ViewModel.SelectedRunId is null) throw new InvalidOperationException("Chọn lượt trước");
        await client.Post($"/v1/runs/{ViewModel.SelectedRunId}/open/{kind}");
    }
    private async void OpenOdb(object sender, RoutedEventArgs e) => await Guard(() => OpenRun("odb"));
    private async void OpenCae(object sender, RoutedEventArgs e) => await Guard(() => OpenRun("cae"));
    private async void OpenPdf(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/runs/{ViewModel.SelectedRunId}/report/export"));
    private async void OpenRunFolder(object sender, RoutedEventArgs e) => await Guard(() => OpenRun("folder"));
    private async void RetryRun(object sender, RoutedEventArgs e) => await Guard(async () => { if (ViewModel.SelectedRunId is null) throw new InvalidOperationException("Chọn lượt"); await client.Post($"/v1/runs/{ViewModel.SelectedRunId}/retry"); await Refresh(); });
    private async Task ExportOperation(string path, JsonNode? body = null)
    {
        var op = await client.Post(path, body); var result = await client.WaitOperation(op, text => Message(text));
        LibraryResult.Text = result.ToJsonString(pretty); Message("Hoàn tất: " + result);
        if (result["path"] is not null) await client.Post("/v1/open", new JsonObject { ["path"] = result["path"]!.ToString() });
    }
    private async void ExportBatchPdf(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/batches/{ViewModel.SelectedBatchId}/report/export"));
    private async void ExportBatchZip(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/batches/{ViewModel.SelectedBatchId}/archive/export"));
    private async void ExportRunZip(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/runs/{ViewModel.SelectedRunId}/archive/export"));
    private async void ExportFieldsCsv(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if(ViewModel.SelectedRunId is null) throw new InvalidOperationException("Chọn lượt trước");
        var field=new TextBox{Header="Field cần xuất (để trống = tất cả)",PlaceholderText="Ví dụ: U, S hoặc PEEQ"};
        var choose=new ContentDialog{Title="Chọn dữ liệu CSV",Content=field,PrimaryButtonText="Dự toán dung lượng",CloseButtonText="Đóng",XamlRoot=Navigation.XamlRoot};
        if(await choose.ShowAsync()!=ContentDialogResult.Primary)return;
        string suffix="?field="+Uri.EscapeDataString(field.Text.Trim());
        var estimate=await client.Get($"/v1/runs/{ViewModel.SelectedRunId}/fields/csv/preview"+suffix);
        double low=estimate["estimated_bytes_range"]![0]!.GetValue<double>()/1e9,high=estimate["estimated_bytes_range"]![1]!.GetValue<double>()/1e9;
        var confirm=new ContentDialog{Title="Dự toán CSV",Content=new TextBlock{Text=$"{estimate["rows"]} bản ghi. Dự kiến {low:0.0}–{high:0.0} GB; ổ đĩa còn {estimate["free_bytes"]!.GetValue<double>()/1e9:0.0} GB. Các trường lớn có thể cần nhiều thời gian. Parquet đầy đủ đã được giữ trong thư viện.",TextWrapping=TextWrapping.Wrap},PrimaryButtonText="Xuất CSV",CloseButtonText="Đóng",XamlRoot=Navigation.XamlRoot};
        if(await confirm.ShowAsync()==ContentDialogResult.Primary) await ExportOperation($"/v1/runs/{ViewModel.SelectedRunId}/fields/csv"+suffix);
    });
    private async Task LoadLibrary()
    {
        var rows = (await client.Get("/v1/runs?q=" + Uri.EscapeDataString(LibrarySearch.Text))).AsArray().Select(r => new RunRow(r!.AsObject()));
        LibraryList.ItemsSource = rows.Where(r => OnlyEligible.IsChecked != true || r.Eligible).ToList();
    }
    private async void SearchLibrary(object sender, RoutedEventArgs e) => await Guard(LoadLibrary);
    private async void ExportDataset(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var ids = new JsonArray(); foreach (var r in LibraryList.SelectedItems.Cast<RunRow>()) ids.Add(r.Id);
        if (ids.Count == 0) throw new InvalidOperationException("Chọn các lượt trong thư viện trước");
        JsonArray? names(string text) => string.IsNullOrWhiteSpace(text) ? null : new JsonArray(text.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).Select(s => JsonValue.Create(s)).ToArray());
        var result = await client.Post("/v1/datasets", new JsonObject { ["run_ids"] = ids, ["name"] = DatasetName.Text, ["seed"] = 42, ["features"] = names(DatasetFeatures.Text), ["targets"] = names(DatasetTargets.Text) });
        LibraryResult.Text = result.ToJsonString(pretty); await client.Post("/v1/open", new JsonObject { ["path"] = result["path"]!.ToString() });
    });
    private async void ShowPareto(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        paretoGroups = (await client.Get("/v1/pareto")).AsArray(); LibraryResult.Text = paretoGroups.ToJsonString(pretty);
        ParetoGroup.ItemsSource = paretoGroups.Select(g => $"{g!["load"]!["energy_J"]} J · M={g["load"]!["mass_kg"]} kg · D={g["load"]!["ball_diameter"]} mm · ({g["load"]!["impact_x"]}, {g["load"]!["impact_y"]})").ToArray();
        ParetoGroup.SelectedIndex = paretoGroups.Count > 0 ? 0 : -1; LibraryTabs.SelectedIndex = 1; DrawPareto();
    });
    private void UpdateParetoPlot(object sender, SelectionChangedEventArgs e) { if (LibraryPlot is not null) DrawPareto(); }
    private void DrawPareto()
    {
        if (LibraryPlot is null) return; LibraryPlot.Plot.Clear();
        if (ParetoGroup.SelectedIndex < 0 || ParetoGroup.SelectedIndex >= paretoGroups.Count) { LibraryPlot.Plot.Title("Chưa có thiết kế đủ chất lượng trong cùng điều kiện tải"); LibraryPlot.Refresh(); return; }
        var group = paretoGroups[ParetoGroup.SelectedIndex]!;
        var xitem = (ComboBoxItem)ParetoX.SelectedItem; var yitem = (ComboBoxItem)ParetoY.SelectedItem;
        string xkey = xitem.Tag!.ToString()!, ykey = yitem.Tag!.ToString()!;
        foreach (string collection in new[] { "all", "front" })
        {
            var valid = group[collection]!.AsArray().Where(r => r?[xkey] is not null && r[ykey] is not null).ToArray();
            if (valid.Length == 0) continue;
            double[] xs = valid.Select(r => r![xkey]!.GetValue<double>() * (xkey == "panel_mass_kg" ? 1000 : 1)).ToArray();
            double[] ys = valid.Select(r => r![ykey]!.GetValue<double>() * (ykey == "panel_mass_kg" ? 1000 : 1)).ToArray();
            var scatter = LibraryPlot.Plot.Add.Scatter(xs, ys); scatter.LineWidth = 0; scatter.MarkerSize = collection == "front" ? 10 : 6;
            scatter.LegendText = collection == "front" ? "Pareto (4 mục tiêu)" : "Thiết kế đủ chất lượng số";
            if (collection == "front") { scatter.MarkerShape = ScottPlot.MarkerShape.OpenCircle; scatter.Color = ScottPlot.Colors.DarkOrange; }
        }
        LibraryPlot.Plot.Title("So sánh cùng tải; physical validation chưa được xác lập");
        LibraryPlot.Plot.XLabel(xitem.Content?.ToString() ?? xkey); LibraryPlot.Plot.YLabel(yitem.Content?.ToString() ?? ykey); LibraryPlot.Plot.ShowLegend(); LibraryPlot.Plot.Axes.AutoScale(); LibraryPlot.Refresh();
    }
    private async void ImportReference(object sender, RoutedEventArgs e) => await Guard(async () => { await ExportOperation("/v1/import-reference", new JsonObject { ["path"] = ReferencePath.Text, ["render"] = true }); await Refresh(); });
    private void WriteSettings()
    {
        if (DataRoot.Text.Any(c => c > 127) || DataRoot.Text.IndexOfAny("&|<>^%!\"\r\n".ToCharArray()) >= 0) throw new InvalidOperationException("Abaqus 2017 cần đường dẫn dữ liệu ASCII, không chứa ký tự điều khiển shell.");
        _ = Path.GetFullPath(DataRoot.Text);
        Directory.CreateDirectory(EngineClient.ConfigDirectory);
        File.WriteAllText(EngineClient.SettingsPath, new JsonObject { ["data_root"] = DataRoot.Text, ["abaqus"] = AbaqusPath.Text }.ToJsonString(pretty));
    }
    private void SaveSettings(object sender, RoutedEventArgs e)
    {
        try { WriteSettings(); Message("Đã lưu cho lần khởi động engine tiếp theo. Job đang chạy giữ nguyên cấu hình."); }
        catch (Exception ex) { Message(ex.Message, true); }
    }
    private async void RestartEngine(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        WriteSettings();
        await client.Post("/v1/engine/shutdown");
        connected = false; timer.Stop(); await Task.Delay(1500); await Initialize();
    });
    private async void Reindex(object sender, RoutedEventArgs e) => await Guard(async () => { Message((await client.Post("/v1/catalog/reindex")).ToJsonString()); await Refresh(); });
    private async void ConnectDrive(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation("/v1/backup/connect", new JsonObject { ["path"] = OAuthClientPath.Text }));
    private async void BackupBatch(object sender, RoutedEventArgs e) => await Guard(async () => { Message((await client.Post("/v1/backup/batches/" + ViewModel.SelectedBatchId)).ToJsonString()); });
    private async void ResumeBackup(object sender, RoutedEventArgs e) => await Guard(async () => { Message((await client.Post("/v1/backup/resume/" + BackupId.Text)).ToJsonString()); });
    private async void RestoreLocal(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation("/v1/backup/restore-local", new JsonObject { ["path"] = RestoreZip.Text }));
    private async void RestoreDrive(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation("/v1/backup/restore-drive", new JsonObject { ["file_id"] = DriveFileId.Text, ["sha256"] = RestoreSha.Text }));
}
