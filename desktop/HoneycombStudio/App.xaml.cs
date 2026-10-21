using Microsoft.UI.Xaml;
namespace HoneycombStudio;
public partial class App : Application
{
    private Window? window;
    public App()
    {
        UnhandledException += (_, e) => LogFailure(e.Exception);
        InitializeComponent();
    }
    private static void LogFailure(Exception exception)
    {
        var folder = EngineClient.ConfigDirectory;
        Directory.CreateDirectory(folder);
        File.AppendAllText(Path.Combine(folder, "desktop-crash.log"), DateTimeOffset.UtcNow + "\n" + exception + "\n");
    }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try { window = new MainWindow(); window.Activate(); }
        catch (Exception ex) { LogFailure(ex); throw; }
    }
}
