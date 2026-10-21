using HoneycombStudio;
using Microsoft.VisualStudio.TestTools.UnitTesting;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;

namespace Desktop.Tests;

[TestClass]
public sealed class ContractTests
{
    [TestMethod]
    public void InitialRefreshSelectsRunningBatchAndItsActiveRun()
    {
        var vm = new StudioViewModel();
        vm.UpdateBatches([
            new BatchRow(JsonNode.Parse("""{"id":"reference","name":"Reference","status":"completed"}""")!.AsObject()),
            new BatchRow(JsonNode.Parse("""{"id":"sweep","name":"Sweep","status":"running"}""")!.AsObject())
        ]);
        Assert.AreEqual("sweep", vm.SelectedBatchId);
        vm.UpdateRuns(Enumerable.Range(1, 13).Select(i => new RunRow(JsonNode.Parse($$"""
        {"id":"r{{i}}","index":{{i}},"status":"{{(i == 8 ? "solving" : i < 8 ? "completed" : "queued")}}","attempts":[]}
        """)!.AsObject())));
        Assert.AreEqual(13, vm.Runs.Count);
        Assert.AreEqual("r8", vm.SelectedRunId);
        vm.SelectedRunId = "r1";
        vm.UpdateRuns(vm.Runs.ToArray());
        Assert.AreEqual("r1", vm.SelectedRunId); // Polling must not steal the user's selection.
    }

    [TestMethod]
    public void PollingPreservesRunIdentityAndDoesNotResetTheList()
    {
        var vm = new StudioViewModel();
        JsonObject Document(double progress) => JsonNode.Parse($$"""
        {"id":"r1","index":1,"status":"solving","phase":"solving",
         "resolved":{"energy_J":7,"velocity_m_s":2.3},"progress":{"solver_percent":{{progress}}},"attempts":[]}
        """)!.AsObject();
        vm.UpdateRuns([new RunRow(Document(10))]);
        var selected = vm.Runs[0];
        int collectionChanges = 0;
        var changed = new List<string?>();
        vm.Runs.CollectionChanged += (_, _) => collectionChanges++;
        selected.PropertyChanged += (_, args) => changed.Add(args.PropertyName);
        vm.UpdateRuns([new RunRow(Document(20))]);
        Assert.AreSame(selected, vm.Runs[0]);
        Assert.AreEqual(0, collectionChanges);
        Assert.AreEqual(20d, selected.Progress);
        CollectionAssert.Contains(changed, nameof(RunRow.Progress));
        changed.Clear();
        vm.UpdateRuns([new RunRow(Document(20))]);
        Assert.AreEqual(0, collectionChanges);
        Assert.IsFalse(changed.Contains(nameof(RunRow.Progress)));
    }

    [TestMethod]
    public async Task ClientFollowsNewEngineSessionWithoutRestartingTheUi()
    {
        using var first = new LocalEngine(1);
        using var second = new LocalEngine(2);
        var file = Path.GetTempFileName();
        try
        {
            void Session(LocalEngine engine) => File.WriteAllText(file,
                new JsonObject { ["url"] = engine.Url, ["token"] = "test-only" }.ToJsonString());
            Session(first);
            var client = new EngineClient(sessionPath: file);
            Assert.AreEqual(1, (await client.Get("/v1/status"))["instance"]!.GetValue<int>());
            Session(second);
            Assert.AreEqual(2, (await client.Get("/v1/status"))["instance"]!.GetValue<int>());
            Assert.AreEqual(2, (await client.Post("/v1/action"))["instance"]!.GetValue<int>());
            Assert.AreEqual(1, second.PostCount);
        }
        finally { File.Delete(file); }
    }

    private sealed class LocalEngine : IDisposable
    {
        private readonly HttpListener listener = new();
        public string Url { get; }
        public int PostCount;
        public LocalEngine(int instance)
        {
            var socket = new System.Net.Sockets.TcpListener(IPAddress.Loopback, 0);
            socket.Start();
            int port = ((IPEndPoint)socket.LocalEndpoint).Port;
            socket.Stop();
            Url = $"http://127.0.0.1:{port}";
            listener.Prefixes.Add(Url + "/");
            listener.Start();
            _ = Task.Run(async () =>
            {
                try
                {
                    while (listener.IsListening)
                    {
                        var context = await listener.GetContextAsync();
                        if (context.Request.HttpMethod == "POST") Interlocked.Increment(ref PostCount);
                        var bytes = Encoding.UTF8.GetBytes(new JsonObject
                        {
                            ["service"] = "honeycomb-studio", ["instance"] = instance
                        }.ToJsonString());
                        context.Response.ContentType = "application/json";
                        context.Response.ContentLength64 = bytes.Length;
                        await context.Response.OutputStream.WriteAsync(bytes);
                        context.Response.Close();
                    }
                }
                catch (Exception ex) when (ex is HttpListenerException or ObjectDisposedException) { }
            });
        }
        public void Dispose() => listener.Close();
    }

    [TestMethod]
    public void RunRowUnderstandsPythonSnakeCaseAndIndependentProgress()
    {
        var row = new RunRow(JsonNode.Parse("""
        {"id":"b_r1","index":1,"status":"extracting","phase":"extracting",
         "resolved":{"energy_J":7.0,"velocity_m_s":2.29848186156},
         "progress":{"solver_percent":100.0,"simulation_time_s":0.006},
         "attempts":[{"number":1}],"quality":{"ml_eligible":false}}
        """)!.AsObject());
        Assert.AreEqual(7.0, row.Energy);
        Assert.AreEqual(0.0, row.Progress); // extraction has its own measured progress
        Assert.AreEqual("extracting", row.Status);
        Assert.IsFalse(row.Eligible);
        Assert.AreEqual("1", row.Attempts);
    }

    [TestMethod]
    public async Task ApiErrorsPreserveBackendExplanation()
    {
        var transport = new HttpClient(new Handler(_ => new HttpResponseMessage(HttpStatusCode.BadRequest) { Content = new StringContent("{\"detail\":\"Bước phải > 0\"}") })) { BaseAddress = new Uri("http://127.0.0.1:12345") };
        var client = new EngineClient(transport);
        try { await client.Post("/v1/preview", new JsonObject()); Assert.Fail("Expected validation failure"); }
        catch (InvalidOperationException e) { StringAssert.Contains(e.Message, "Bước phải > 0"); }
    }

    [TestMethod]
    public async Task PostTransmitsCompleteUnicodeInputJson()
    {
        string? captured = null;
        var transport = new HttpClient(new AsyncHandler(async request =>
        {
            captured = await request.Content!.ReadAsStringAsync();
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("{\"id\":\"b1\"}", Encoding.UTF8, "application/json") };
        })) { BaseAddress = new Uri("http://127.0.0.1:12345") };
        var client = new EngineClient(transport);
        var input = JsonNode.Parse("{\"name\":\"Khảo sát\",\"model\":{\"foil\":0.0635,\"mass_kg\":2.65}}")!;
        var result = await client.Post("/v1/batches", input);
        Assert.AreEqual("b1", result["id"]!.ToString());
        Assert.AreEqual(0.0635, JsonNode.Parse(captured!)!["model"]!["foil"]!.GetValue<double>());
        Assert.AreEqual("Khảo sát", JsonNode.Parse(captured!)!["name"]!.ToString());
    }

    [TestMethod]
    public void UnknownProgressDoesNotInventElapsedTime()
    {
        var row = new RunRow(JsonNode.Parse("{\"id\":\"r\",\"index\":1,\"status\":\"building\",\"phase\":\"building\",\"resolved\":{\"energy_J\":7,\"velocity_m_s\":2.3},\"attempts\":[]}")!.AsObject());
        Assert.IsTrue(row.Indeterminate);
        Assert.AreEqual(0.0, row.Progress);
        StringAssert.Contains(row.Timing, "ETA —");
    }

    private sealed class Handler(Func<HttpRequestMessage, HttpResponseMessage> handle) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => Task.FromResult(handle(request));
    }
    private sealed class AsyncHandler(Func<HttpRequestMessage, Task<HttpResponseMessage>> handle) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) => handle(request);
    }
}
