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
