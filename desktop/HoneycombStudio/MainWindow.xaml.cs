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
    private readonly EngineClient client = new(sessionPath: Environment.GetEnvironmentVariable("HONEYCOMB_STUDIO_SESSION"));
    private readonly DispatcherTimer timer = new() { Interval = TimeSpan.FromSeconds(2) };
    private JsonObject model = new();
    private JsonObject baseSpec = new();
    private JsonArray parameters = new();
    private readonly List<AxisEditor> axes = [];
    private readonly Dictionary<string,NumberBox> loadingEditors=[];
    private bool synchronizingLoading;
    private TextBlock? geometryFormula, impactFormula;
    private List<BatchRow> batchRows = [];
    private List<RunRow> runRows = [];
    private JsonArray historyRows = new();
    private JsonArray paretoGroups = new();
    private bool connected, refreshing, updatingLists;
    private int eventCursor;
    private string? lastDatasetId;
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
        var title = error ? "Cần xử lý" : "Honeycomb Studio";
        var text = message.Length > 700 ? message[..700] + "… Xem log hoặc chi tiết lượt để đọc đầy đủ." : message;
        if (Banner.IsOpen && Banner.Title == title && Banner.Message == text) return;
        Banner.Title = title;
        Banner.Message = text;
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
                var selectedBatchId = ViewModel.SelectedBatchId;
                var detail = await client.Get("/v1/batches/" + selectedBatchId);
                if (ViewModel.SelectedBatchId != selectedBatchId) return;
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

    private static string Group(string key) => key.StartsWith("face_material") ? "Vật liệu mặt" : key.StartsWith("core_material") ? "Vật liệu lõi" : key.Contains("seed") || key.Contains("divisions") || key is "mesh_preset" or "fine_radius" or "skin_patch_half" or "shell_points" or "shell_element" ? "Lưới" : key is "loading" or "energy_J" or "velocity_m_s" or "mass_kg" or "ball_diameter" or "ball_radius" or "ball_size_mode" or "impact_x" or "impact_y" or "gap" or "gravity" ? "Va đập" : key.Contains("contact") || key.Contains("bond") || key.Contains("friction") || key.Contains("tie") || key.StartsWith("clamp_") ? "Liên kết và điều kiện biên" : key.Contains("interval") || key.Contains("variables") || key is "duration" or "cpus" or "precision" or "mass_scaling" or "bulk_linear" or "bulk_quadratic" ? "Solver và output" : "Hình học";
    private JsonNode? Value(string key)
    {
        JsonNode? n = model; foreach (var part in key.Split('.')) n = n?[part]; return n;
    }
    private void SetValue(string key, JsonNode? value)
    {
        JsonObject node = model;
        var parts = key.Split('.'); foreach (var part in parts[..^1]) node = node[part]!.AsObject();
        node[parts[^1]] = value;
        if(key is "loading" or "energy_J" or "velocity_m_s" or "mass_kg") UpdateLoadingEditors();
        if (key is "ball_radius" or "ball_diameter" or "ball_size_mode")
        {
            if (Value("ball_size_mode")?.ToString() == "radius") model["ball_diameter"] = Number("ball_radius", 6.55) * 2;
            else model["ball_radius"] = Number("ball_diameter", 13.1) / 2;
        }
        UpdateFormulaText();
    }
    private double Number(string key, double fallback) => Value(key)?.GetValue<double>() ?? fallback;
    private void UpdateFormulaText()
    {
        if (geometryFormula is not null)
        {
            double t = Number("foil", .0635), rho = Number("core_material.density", 2700);
            if (Value("core_topology")?.ToString() == "reentrant_0")
            {
                double w = Number("cell_size", 6.35), h = Number("reentrant_cell_height", 5), a = Number("reentrant_indent", 1.25);
                if (Value("reentrant_geometry")?.ToString() == "angle") a = h / 2 * Math.Tan(Number("reentrant_delta_deg", 26.56505117707799) * Math.PI / 180);
                double l = Math.Sqrt(a*a+h*h/4);
                double density = (2*w+2*l)*t*rho/((w-a)*h);
                geometryFormula.Text = $"Ô lõm: HD = (2w + 2l)tρ / [(w − a)h], l = √(a² + (h/2)²)\nw = {w:G6}; h = {h:G6}; a = {a:G6}; t = {t:G6} mm; ρ = {rho:G6} kg/m³ → HD = {density:G6} kg/m³";
            }
            else
            {
                bool custom = Value("hex_geometry")?.ToString() == "parametric";
                double b = custom ? Number("hex_b", 3.666) : Number("cell_size", 6.35)/Math.Sqrt(3);
                double l = custom ? Number("hex_l", 3.666) : b;
                double angle = custom ? Number("hex_theta_deg", 60) : 60, theta = angle*Math.PI/180;
                double width = 2*l*Math.Sin(theta), pitch = b+l*Math.Cos(theta);
                double density = 2*(b+l)*t*rho/(pitch*width);
                geometryFormula.Text = $"HD = 2(b + l)tρ / [(b + l cosθ)(2l sinθ)]\nb = {b:G6}; l = {l:G6}; θ = {angle:G6}°; t = {t:G6} mm; ρ = {rho:G6} kg/m³\n2l sinθ = {width:G6} mm; b + l cosθ = {pitch:G6} mm → HD = {density:G6} kg/m³\nÔ đều: b = l, θ = 60° → HD ≈ 1,54tρ/b. Vách đứng dày 2t; vách nghiêng dày t.";
            }
        }
        if (impactFormula is not null)
        {
            double radius = Value("ball_size_mode")?.ToString() == "radius" ? Number("ball_radius",6.55) : Number("ball_diameter",13.1)/2;
            impactFormula.Text = $"E = ½mv² · D = 2R = {2*radius:G6} mm · R = {radius:G6} mm\nKhối lượng chuyển động m được nhập riêng; đổi bán kính không tự đổi m.";
        }
    }
    private void UpdateLoadingEditors()
    {
        if(synchronizingLoading)return;
        synchronizingLoading=true;
        try
        {
            double mass=model["mass_kg"]?.GetValue<double>()??0;
            if(mass<=0)return;
            string dependent=model["loading"]?.ToString()=="velocity"?"energy_J":"velocity_m_s";
            double independent=model[dependent=="energy_J"?"velocity_m_s":"energy_J"]?.GetValue<double>()??0;
            if(independent<0)return;
            double calculated=dependent=="energy_J"?.5*mass*independent*independent:Math.Sqrt(2*independent/mass);
            if(double.IsFinite(calculated)){model[dependent]=calculated;if(loadingEditors.TryGetValue(dependent,out var box))box.Value=calculated;}
        }
        finally{synchronizingLoading=false;}
    }
    private void BuildParameterForm()
    {
        UpdateLoadingEditors();loadingEditors.Clear();
        ParameterGroups.Children.Clear();
        geometryFormula = impactFormula = null;
        bool reentrant = Value("core_topology")?.ToString() == "reentrant_0";
        foreach (var group in parameters.Select(p => p!.AsObject()).GroupBy(p => Group(p["key"]!.ToString())))
        {
            var stack = new StackPanel { Spacing = 10, Padding = new Thickness(4, 12, 4, 12) };
            if (group.Key == "Hình học") { geometryFormula = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0,0,0,12) }; stack.Children.Add(geometryFormula); }
            if (group.Key == "Va đập") { impactFormula = new TextBlock { TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0,0,0,12) }; stack.Children.Add(impactFormula); }
            foreach (var descriptor in group)
            {
                string key = descriptor["key"]!.ToString(); string unit = descriptor["unit"]?.ToString() ?? "";
                if (reentrant && key.StartsWith("hex_")) continue;
                if (!reentrant && Value("hex_geometry")?.ToString() == "parametric" && key == "cell_size") continue;
                if (!reentrant && Value("hex_geometry")?.ToString() != "parametric" && key is "hex_b" or "hex_l" or "hex_theta_deg") continue;
                if (key == "ball_radius" && Value("ball_size_mode")?.ToString() != "radius") continue;
                if (key == "ball_diameter" && Value("ball_size_mode")?.ToString() == "radius") continue;
                if (key == "clamp_diameter" && Value("clamp_mode")?.ToString() == "perimeter") continue;
                if (!reentrant && (key.StartsWith("reentrant_") || key == "phase_z")) continue;
                if (key == "reentrant_indent" && Value("reentrant_geometry")?.ToString() == "angle") continue;
                if (key == "reentrant_delta_deg" && Value("reentrant_geometry")?.ToString() != "angle") continue;
                if (reentrant && key is "core_angle" or "phase_y" or "core_z_divisions") continue;
                var row = new Grid { ColumnSpacing = 16 };
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(310) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(240) });
                row.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
                var label = new TextBlock { Text = descriptor["title"] + (unit.Length > 0 ? " (" + unit + ")" : ""), VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };
                if (reentrant && key == "cell_size") label.Text = "Bề rộng bao ô lõm (mm)";
                if (reentrant && key == "fine_radius") label.Text = "Nửa rộng vùng tinh lưới lõi X (mm)";
                ToolTipService.SetToolTip(label, key); row.Children.Add(label);
                bool derivedLoading=key==(model["loading"]?.ToString()=="velocity"?"energy_J":"velocity_m_s");
                string mode=derivedLoading?"Suy ra E=½mv²":axes.Any(a=>a.Key.SelectedItem?.ToString()==key)?"Khảo sát":"Cố định";
                var source = new TextBlock { Text = mode+" · "+descriptor["source"]?.ToString(), FontSize = 12, Opacity = .8, TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center }; Grid.SetColumn(source, 2); row.Children.Add(source);
                if (key == "core_topology") source.Text = reentrant ? "Ô lõm XZ, đùn theo Y · kích thước giả định, chưa hội tụ" : "Ô lục giác XY, đùn theo Z · mô hình tham chiếu";
                var current = Value(key) ?? descriptor["default"];
                FrameworkElement editor;
                var options = key switch
                {
                    "mesh_preset" => new[] { "reference", "quick", "fine", "custom" },
                    "face_material.hardening" or "core_material.hardening" => ["shifted_ramberg_osgood", "perfect_plastic", "bilinear", "table"],
                    _ => Array.Empty<string>()
                };
                if (key == "core_topology")
                {
                    var combo = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
                    combo.Items.Add(new ComboBoxItem { Content = "Tổ ong lục giác", Tag = "hexagonal" });
                    combo.Items.Add(new ComboBoxItem { Content = "Tổ ong lõm (Re-entrant) — 0°", Tag = "reentrant_0" });
                    combo.SelectedIndex = reentrant ? 1 : 0;
                    combo.SelectionChanged += (_, _) =>
                    {
                        if (combo.SelectedItem is not ComboBoxItem selected) return;
                        string topology = selected.Tag.ToString()!;
                        SetValue(key, JsonValue.Create(topology));
                        if (topology == "reentrant_0")
                        {
                            SetValue("core_angle", JsonValue.Create(0.0));
                            SetValue("phase_y", JsonValue.Create(0.0));
                        }
                        foreach (var axis in axes)
                        {
                            string? selectedKey = axis.Key.SelectedItem?.ToString();
                            var keys = AxisParameterKeys();
                            // Preserve an existing axis for review; Preview explains inactive parameters.
                            if (selectedKey is not null && !keys.Contains(selectedKey)) keys = [.. keys, selectedKey];
                            axis.Key.ItemsSource = keys;
                            axis.Key.SelectedItem = selectedKey;
                        }
                        DispatcherQueue.TryEnqueue(BuildParameterForm);
                    };
                    editor = combo;
                }
                else if (key is "hex_geometry" or "ball_size_mode" or "loading" or "reentrant_geometry")
                {
                    var combo = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
                    var choices = key switch
                    {
                        "hex_geometry" => new[] { ("Ô đều theo kích thước ô", "regular"), ("Nhập b, l, θ", "parametric") },
                        "reentrant_geometry" => new[] { ("Nhập độ lõm d", "indent"), ("Nhập góc δ với phương đứng", "angle") },
                        "ball_size_mode" => new[] { ("Nhập bán kính R", "radius"), ("Nhập đường kính D", "diameter") },
                        _ => new[] { ("Nhập năng lượng E (J)", "energy"), ("Nhập vận tốc v (m/s)", "velocity") }
                    };
                    foreach (var (title, tag) in choices) combo.Items.Add(new ComboBoxItem { Content = title, Tag = tag });
                    combo.SelectedIndex = Array.FindIndex(choices, c => c.Item2 == current?.ToString());
                    combo.SelectionChanged += (_, _) =>
                    {
                        if (combo.SelectedItem is not ComboBoxItem selected) return;
                        string mode = selected.Tag.ToString()!;
                        if (key == "reentrant_geometry" && mode != Value(key)?.ToString())
                        {
                            double height = Number("reentrant_cell_height", 5);
                            if (mode == "angle") SetValue("reentrant_delta_deg", JsonValue.Create(Math.Atan2(Number("reentrant_indent", 1.25), height / 2) * 180 / Math.PI));
                            else SetValue("reentrant_indent", JsonValue.Create(height / 2 * Math.Tan(Number("reentrant_delta_deg", 26.56505117707799) * Math.PI / 180)));
                        }
                        if (key == "hex_geometry" && mode == "parametric")
                        {
                            SetValue("hex_b", JsonValue.Create(Number("cell_size", 6.35)/Math.Sqrt(3)));
                            SetValue("hex_l", JsonValue.Create(Number("cell_size", 6.35)/Math.Sqrt(3)));
                            SetValue("hex_theta_deg", JsonValue.Create(60.0));
                        }
                        SetValue(key, JsonValue.Create(mode));
                        foreach (var axis in axes)
                        {
                            string? old = axis.Key.SelectedItem?.ToString();
                            string? next = key == "loading" && old is "energy_J" or "velocity_m_s" ? (mode == "energy" ? "energy_J" : "velocity_m_s")
                                : key == "ball_size_mode" && old is "ball_radius" or "ball_diameter" ? (mode == "radius" ? "ball_radius" : "ball_diameter") : old;
                            if (next != old && next is not null)
                            {
                                if (key == "loading")
                                {
                                    double mass = Number("mass_kg", 2.65);
                                    double ConvertLoad(double x) => mode == "energy" ? .5*mass*x*x : Math.Sqrt(2*x/mass);
                                    // Convert explicit points, preserving physical values across modes.
                                    var points = string.IsNullOrWhiteSpace(axis.Values.Text) ? null : JsonNode.Parse(axis.Values.Text)?.AsArray();
                                    if (points is not null) axis.Values.Text = new JsonArray(points.Select(p => (JsonNode?)JsonValue.Create(ConvertLoad(p!.GetValue<double>()))).ToArray()).ToJsonString();
                                    else { axis.Start.Value = ConvertLoad(axis.Start.Value); axis.Stop.Value = ConvertLoad(axis.Stop.Value); axis.Step.Value = mode == "energy" ? 1 : .2; }
                                }
                                else
                                {
                                    double factor = mode == "radius" ? .5 : 2;
                                    if (!string.IsNullOrWhiteSpace(axis.Values.Text))
                                    {
                                        var points = JsonNode.Parse(axis.Values.Text)!.AsArray();
                                        axis.Values.Text = new JsonArray(points.Select(p => (JsonNode?)JsonValue.Create(p!.GetValue<double>()*factor)).ToArray()).ToJsonString();
                                    }
                                    axis.Start.Value *= factor; axis.Stop.Value *= factor; axis.Step.Value *= factor;
                                }
                            }
                            var keys = AxisParameterKeys();
                            if (next is not null && !keys.Contains(next)) keys = [.. keys, next];
                            axis.Key.ItemsSource = keys; axis.Key.SelectedItem = next;
                        }
                        DispatcherQueue.TryEnqueue(BuildParameterForm);
                    };
                    editor = combo;
                }
                else if (key == "clamp_mode")
                {
                    var combo = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch };
                    combo.Items.Add(new ComboBoxItem { Content = "Chỉ bốn cạnh ngoài", Tag = "perimeter" });
                    combo.Items.Add(new ComboBoxItem { Content = "Vùng ngoài lỗ tròn", Tag = "circular" });
                    combo.SelectedIndex = current?.ToString() == "perimeter" ? 0 : 1;
                    source.Text = "Khóa 6 bậc tự do trên cả hai tấm mặt";
                    combo.SelectionChanged += (_, _) =>
                    {
                        if (combo.SelectedItem is not ComboBoxItem selected) return;
                        SetValue(key, JsonValue.Create(selected.Tag.ToString()));
                        foreach (var axis in axes)
                        {
                            string? old = axis.Key.SelectedItem?.ToString();
                            var keys = AxisParameterKeys();
                            if (old is not null && !keys.Contains(old)) keys = [.. keys, old];
                            axis.Key.ItemsSource = keys;
                            axis.Key.SelectedItem = old;
                        }
                        DispatcherQueue.TryEnqueue(BuildParameterForm);
                    };
                    editor = combo;
                }
                else if (options.Length > 0)
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
                        if (key is "mesh_preset" or "loading") DispatcherQueue.TryEnqueue(BuildParameterForm);
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
                    if(key is "energy_J" or "velocity_m_s" or "mass_kg")loadingEditors[key]=box;
                    if(derivedLoading)box.IsEnabled=false;
                    if (descriptor["type"]?.ToString().Contains("Literal") == true || key == "impactor_poisson") box.IsEnabled = false;
                    if ((key.Contains("seed") || key == "core_z_divisions") && model["mesh_preset"]?.ToString() != "custom") { box.IsEnabled = false; source.Text += " · theo preset; chọn custom để sửa"; }
                    box.ValueChanged += (_, args) =>
                    {
                        if (double.IsFinite(args.NewValue) && !synchronizingLoading) SetValue(key, JsonValue.Create(args.NewValue));
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
        UpdateFormulaText();
    }
    private sealed record AxisEditor(Grid Row, ComboBox Key, NumberBox Start, NumberBox Stop, NumberBox Step, CheckBox End, TextBox Values);
    private string[] AxisParameterKeys()
    {
        bool reentrant = Value("core_topology")?.ToString() == "reentrant_0";
        return parameters.Select(p => p!.AsObject())
            .Where(p => p["sweep_allowed"]?.GetValue<bool>() != false && (p["type"]?.ToString().Contains("Literal") != true || p["key"]!.ToString().EndsWith(".hardening")))
            .Select(p => p["key"]!.ToString())
            .Where(k => Value(k) is JsonValue v && v.TryGetValue<double>(out _) || k == "bottom_skin" || k.EndsWith(".hardening"))
            .Where(k => reentrant ? k is not ("core_angle" or "phase_y" or "core_z_divisions") : !k.StartsWith("reentrant_") && k != "phase_z")
            .Where(k => k != (Value("reentrant_geometry")?.ToString() == "angle" ? "reentrant_indent" : "reentrant_delta_deg"))
            .Where(k => k != "clamp_diameter" || Value("clamp_mode")?.ToString() != "perimeter")
            .Where(k => !k.StartsWith("hex_") || !reentrant && Value("hex_geometry")?.ToString() == "parametric")
            .Where(k => k != "cell_size" || reentrant || Value("hex_geometry")?.ToString() != "parametric")
            .Where(k => k != (Value("ball_size_mode")?.ToString() == "radius" ? "ball_diameter" : "ball_radius"))
            .ToArray();
    }
    private void AddAxisEditor(string key = "core_height", double start = 15, double stop = 25, double step = 5)
    {
        var panel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        var numericKeys = AxisParameterKeys();
        var combo = new ComboBox { Header = "Tham số", ItemsSource = numericKeys, SelectedItem = key, Width = 250 };
        var a = new NumberBox { Header = "Đầu", Value = start, Width = 105 };
        var b = new NumberBox { Header = "Cuối", Value = stop, Width = 105 };
        var h = new NumberBox { Header = "Bước", Value = step, Width = 105 };
        var end = new CheckBox { Content = "Thêm điểm cuối", VerticalAlignment = VerticalAlignment.Bottom };
        var vals = new TextBox { Header = "Hoặc danh sách (JSON)", PlaceholderText = "[0.85, 2, 7, 13]", Width = 230 };
        var remove = new Button { Content = "Bỏ", VerticalAlignment = VerticalAlignment.Bottom };
        foreach (var control in new FrameworkElement[] { combo, a, b, h, end, vals, remove }) panel.Children.Add(control);
        combo.SelectionChanged += (_, _) => { if (combo.SelectedItem?.ToString()?.EndsWith(".hardening") == true) vals.Text = "[\"perfect_plastic\",\"shifted_ramberg_osgood\",\"bilinear\"]"; DispatcherQueue.TryEnqueue(BuildParameterForm); };
        var row = new Grid(); row.Children.Add(new ScrollViewer { Content = panel, HorizontalScrollMode = ScrollMode.Enabled, HorizontalScrollBarVisibility = ScrollBarVisibility.Auto, VerticalScrollMode = ScrollMode.Disabled }); var editor = new AxisEditor(row, combo, a, b, h, end, vals); axes.Add(editor); AxesPanel.Children.Add(row);
        remove.Click += (_, _) => { axes.Remove(editor); AxesPanel.Children.Remove(row); BuildParameterForm(); };
        BuildParameterForm();
    }
    private void AddAxis(object sender, RoutedEventArgs e) => AddAxisEditor(model["loading"]?.ToString()=="velocity"?"velocity_m_s":"energy_J");
    private JsonObject Spec()
    {
        var spec = baseSpec.DeepClone().AsObject(); spec["name"] = BatchName.Text; spec["model"] = model.DeepClone();
        spec["sampling"] = ((ComboBoxItem)SamplingMode.SelectedItem).Tag!.ToString();
        spec["samples"] = (int)SampleCount.Value; spec["seed"] = (int)RandomSeed.Value;
        spec["project_id"] = ProjectName.Text; spec["notes"] = StudyNotes.Text;
        spec["runtime_budget_minutes"] = RuntimeBudget.Value; spec["min_free_gb"] = DiskReserve.Value;
        spec["min_available_ram_gb"] = RamReserve.Value; spec["max_runs"] = (int)MaxRuns.Value;
        spec["execution_mode"] = ((ComboBoxItem)ExecutionMode.SelectedItem).Tag!.ToString();
        spec["max_parallel_runs"] = (int)MaxParallelRuns.Value; spec["ram_per_run_gb"] = RamPerRun.Value;
        spec["export_all_fields"] = FullFieldArchive.IsChecked == true; spec["render_images"] = RenderImages.IsChecked == true; spec["backup_after_run"] = BackupAfterRun.IsChecked == true;
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
        if (preview["execution"] is JsonObject execution) PreviewSummary.Text += $"\nĐồng thời dự kiến {execution["effective_parallel_runs"]}/{execution["requested_parallel_runs"]} lượt; {execution["cpu_per_run"]} CPU/lượt. Worker kiểm tra lại tài nguyên trước khi cấp lượt.";
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
        ViewModel.UpdateBatches(batchRows.Where(b => b.Name.Contains(JobSearch.Text, StringComparison.OrdinalIgnoreCase)));
        var selected = ViewModel.Batches.FirstOrDefault(b => b.Id == ViewModel.SelectedBatchId);
        if (!ReferenceEquals(JobList.SelectedItem, selected)) JobList.SelectedItem = selected;
    }
    private void FilterJobs(object sender, TextChangedEventArgs e) { if (!updatingLists) { updatingLists = true; ApplyJobFilter(); updatingLists = false; } }
    private async void SelectBatch(object sender, SelectionChangedEventArgs e)
    {
        if (updatingLists || JobList.SelectedItem is not BatchRow b) return;
        ViewModel.SelectedBatchId = b.Id; ViewModel.SelectedRunId = null;
        SelectedRunTitle.Text = "Chọn một lượt để xem input và kết quả";
        RunInputs.ItemsSource = null; RunOutputs.ItemsSource = null; RunAttempts.ItemsSource = null;
        RunDetailJson.Text = ""; RunLogs.Text = ""; historyRows = new(); PlotHistory(); FigureGallery.Children.Clear();
        await Guard(Refresh);
    }
    private void ApplyRunSort()
    {
        updatingLists = true;
        IEnumerable<RunRow> ordered = RunSort.SelectedIndex switch { 1 => runRows.OrderBy(r => r.Energy), 2 => runRows.OrderBy(r => r.Status), _ => runRows.OrderBy(r => int.Parse(r.Index)) };
        string filter = (RunFilter?.SelectedItem as ComboBoxItem)?.Tag?.ToString() ?? "";
        ViewModel.UpdateRuns(ordered.Where(r => filter.Length == 0 || r.Status == filter));
        var selected = ViewModel.Runs.FirstOrDefault(r => r.Id == ViewModel.SelectedRunId);
        if (!ReferenceEquals(RunList.SelectedItem, selected)) RunList.SelectedItem = selected;
        updatingLists = false;
    }
    private void UpdateColumns(object sender,RoutedEventArgs e)
    {
        ColumnSettings.Current.Status=ShowStatusColumn.IsChecked?Visibility.Visible:Visibility.Collapsed;
        ColumnSettings.Current.Phase=ShowPhaseColumn.IsChecked?Visibility.Visible:Visibility.Collapsed;
        ColumnSettings.Current.Attempt=ShowAttemptColumn.IsChecked?Visibility.Visible:Visibility.Collapsed;
        StatusHeader.Visibility=ColumnSettings.Current.Status;PhaseHeader.Visibility=ColumnSettings.Current.Phase;AttemptHeader.Visibility=ColumnSettings.Current.Attempt;
        RunTable.MinWidth=1200-(ShowStatusColumn.IsChecked?0:100)-(ShowPhaseColumn.IsChecked?0:160)-(ShowAttemptColumn.IsChecked?0:100);
        ApplyRunSort();
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
        var selectedRunId = ViewModel.SelectedRunId;
        var run = await client.Get("/v1/runs/" + selectedRunId);
        if (ViewModel.SelectedRunId != selectedRunId) return;
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
          if (ViewModel.SelectedRunId != selectedRunId) return;
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
        var logs = await client.Get("/v1/runs/" + selectedRunId + "/logs");
        var history = await client.Get("/v1/runs/" + selectedRunId + "/history");
        if (ViewModel.SelectedRunId != selectedRunId) return;
        RunLogs.Text = logs.ToJsonString(pretty);
        historyRows = history.AsArray(); PlotHistory();
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
                using var stream = await file.OpenReadAsync(); await bitmap.SetSourceAsync(stream);
                if (ViewModel.SelectedRunId != selectedRunId) return;
                image.Source = bitmap;
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
        await ShowExportResult(result);
    }
    private async Task ShowExportResult(JsonNode result)
    {
        LibraryResult.Text = result.ToJsonString(pretty); Message("Hoàn tất: " + result);
        if (result["path"] is not null) await client.Post("/v1/open", new JsonObject { ["path"] = result["path"]!.ToString() });
    }
    private async void ExportBatchPdf(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/batches/{ViewModel.SelectedBatchId}/report/export"));
    private async void ExportBatchDocx(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/batches/{ViewModel.SelectedBatchId}/report/export?format=docx"));
    private async void ExportRunDocx(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/runs/{ViewModel.SelectedRunId}/report/export?format=docx"));
    private async void ExportBatchResearch(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (ViewModel.SelectedBatchId is null) throw new InvalidOperationException("Chọn job trước");
        await ShowExportResult(await client.ExportBatchDataset(ViewModel.SelectedBatchId, text => Message(text)));
    });
    private async void ExportBatchZip(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/batches/{ViewModel.SelectedBatchId}/archive/export"));
    private async void ExportRunZip(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation($"/v1/runs/{ViewModel.SelectedRunId}/archive/export"));
    private async void ExportRunResearch(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if(ViewModel.SelectedRunId is null) throw new InvalidOperationException("Chọn lượt trước");
        var result = await client.Post("/v1/datasets",new JsonObject { ["run_ids"] = new JsonArray(ViewModel.SelectedRunId), ["name"] = "Dữ liệu tối ưu honeycomb" });
        lastDatasetId=result["id"]!.ToString();
        await client.Post("/v1/open",new JsonObject{["path"]=result["path"]!.ToString()});
        Message("Đã xuất samples.csv/Parquet: mỗi lượt một dòng, kèm đường cong và từ điển cột. Không xuất bảng nút/phần tử khổng lồ.");
    });
    private async void ExportFieldsCsv(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if(ViewModel.SelectedRunId is null) throw new InvalidOperationException("Chọn lượt trước");
        var field=new TextBox{Header="Field cần xuất (để trống = tất cả)",PlaceholderText="Ví dụ: U, S hoặc PEEQ"};
        var choose=new ContentDialog{Title="Chọn dữ liệu CSV",Content=field,PrimaryButtonText="Dự toán dung lượng",CloseButtonText="Đóng",XamlRoot=Navigation.XamlRoot};
        if(await choose.ShowAsync()!=ContentDialogResult.Primary)return;
        string suffix="?field="+Uri.EscapeDataString(field.Text.Trim());
        var estimate=await client.Get($"/v1/runs/{ViewModel.SelectedRunId}/fields/csv/preview"+suffix);
        double low=estimate["estimated_bytes_range"]![0]!.GetValue<double>()/1e9,high=estimate["estimated_bytes_range"]![1]!.GetValue<double>()/1e9;
        var confirm=new ContentDialog{Title="CSV nút/phần tử - không cần cho ML dạng bảng",Content=new TextBlock{Text=$"{estimate["rows"]} bản ghi. Dự kiến {low:0.0}–{high:0.0} GB; ổ đĩa còn {estimate["free_bytes"]!.GetValue<double>()/1e9:0.0} GB. Đây là dữ liệu mọi nút/phần tử qua các frame, KHÔNG phải bảng mỗi lượt một dòng. Để huấn luyện/tối ưu, chọn Dữ liệu ML gọn. ODB gốc được giữ trong thư viện.",TextWrapping=TextWrapping.Wrap},PrimaryButtonText="Xuất CSV",CloseButtonText="Đóng",XamlRoot=Navigation.XamlRoot};
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
        lastDatasetId=result["id"]!.ToString();LibraryResult.Text = result.ToJsonString(pretty); await client.Post("/v1/open", new JsonObject { ["path"] = result["path"]!.ToString() });
    });
    private async void ExportDatasetZip(object sender,RoutedEventArgs e)=>await Guard(async()=>
    {
        if(lastDatasetId is null)throw new InvalidOperationException("Xuất dataset từ các lượt đã chọn trước, sau đó đóng gói ZIP.");
        await ExportOperation($"/v1/datasets/{lastDatasetId}/archive/export");
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
    private async void CheckDrive(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation("/v1/backup/check"));
    private async Task RequireReadableBackup()
    {
        var health = await client.Get("/health");
        if (health["capabilities"] is not JsonArray capabilities || !capabilities.Any(c => c?.ToString() == "readable_backup"))
            throw new InvalidOperationException("Engine đang chạy bản cũ chỉ backup ZIP. Chờ upload hiện tại hoàn tất, rồi chọn Lưu và khởi động lại engine để backup cả PDF và dữ liệu huấn luyện riêng.");
    }
    private async void BackupBatch(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (ViewModel.SelectedBatchId is null) throw new InvalidOperationException("Chọn job trước");
        await RequireReadableBackup();
        Message((await client.Post("/v1/backup/batches/" + ViewModel.SelectedBatchId)).ToJsonString());
    });
    private async void BackupReadable(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        if (ViewModel.SelectedBatchId is null) throw new InvalidOperationException("Chọn job trước");
        await RequireReadableBackup();
        Message((await client.Post($"/v1/backup/batches/{ViewModel.SelectedBatchId}/readable")).ToJsonString());
    });
    private async void OpenRetained(object sender, RoutedEventArgs e) => await Guard(async () =>
    {
        var status = await client.Get("/v1/backup");
        if (status["retained_root"] is null) throw new InvalidOperationException("Khởi động lại engine để mở thư mục báo cáo và dữ liệu giữ lại.");
        await client.Post("/v1/open", new JsonObject { ["path"] = status["retained_root"]!.ToString() });
    });
    private async void ResumeBackup(object sender, RoutedEventArgs e) => await Guard(async () => { Message((await client.Post("/v1/backup/resume/" + BackupId.Text)).ToJsonString()); });
    private async void RestoreLocal(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation("/v1/backup/restore-local", new JsonObject { ["path"] = RestoreZip.Text }));
    private async void RestoreDrive(object sender, RoutedEventArgs e) => await Guard(() => ExportOperation("/v1/backup/restore-drive", new JsonObject { ["file_id"] = DriveFileId.Text, ["sha256"] = RestoreSha.Text }));
}

public sealed class ColumnSettings : CommunityToolkit.Mvvm.ComponentModel.ObservableObject
{
    public static ColumnSettings Current { get; } = new();
    private Visibility status = Visibility.Visible, phase = Visibility.Visible, attempt = Visibility.Visible;
    public Visibility Status { get => status; set => SetProperty(ref status, value); }
    public Visibility Phase { get => phase; set => SetProperty(ref phase, value); }
    public Visibility Attempt { get => attempt; set => SetProperty(ref attempt, value); }
}
