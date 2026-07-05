using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using Npgsql;
using RiskSignalApi.Middleware;
using RiskSignalApi.Models;
using RiskSignalApi.Services;

var builder = WebApplication.CreateBuilder(args);

// --- Artifacts (copied next to the binary by the .csproj) ---
string artifacts = Path.Combine(AppContext.BaseDirectory, "artifacts");
var tokenizer = new TokenizerService(Path.Combine(artifacts, "vocab.txt"));
var scorer = new ScoringService(Path.Combine(artifacts, "finbert.onnx"), tokenizer);
string referencePath = Path.Combine(artifacts, "parity_reference.json");

// --- Postgres (connection string from config, env var, or localhost default) ---
string connString =
    builder.Configuration.GetConnectionString("Postgres")
    ?? Environment.GetEnvironmentVariable("RISK_DB_CONNECTION")
    ?? "Host=localhost;Port=5432;Database=risk_signal_db;Username=postgres;Password=postgres";
var dataSource = NpgsqlDataSource.Create(connString);

builder.Services.AddSingleton(tokenizer);
builder.Services.AddSingleton(scorer);
builder.Services.AddSingleton(dataSource);
builder.Services.AddSingleton<PostgresService>();

var app = builder.Build();

// API-key gate (skips /health and /parity). Registered before endpoints so it runs first.
app.UseMiddleware<ApiKeyMiddleware>();

app.MapGet("/health", () => Results.Ok(new { status = "ok" }));

// --- Scoring (protected) ---
app.MapPost("/score", async (ScoreRequest req, ScoringService svc, PostgresService pg) =>
{
    if (string.IsNullOrWhiteSpace(req.Text))
        return Results.BadRequest(new { error = "text is required" });

    var sw = Stopwatch.StartNew();
    ScoreResult result = svc.Score(req.Text);
    sw.Stop();

    // Best-effort logging: a logging failure must not fail the scoring request.
    try
    {
        string inputFeatures = JsonSerializer.Serialize(new
        {
            text_sha256 = PostgresService.HashKey(req.Text),
            token_count = result.TokenCount
        });
        string contributions = JsonSerializer.Serialize(result.Scores);
        double confidence = result.Scores.Values.Max();

        await pg.LogPredictionAsync(new PredictionLog(
            ModelVersion: "finbert-base",
            InputFeaturesJson: inputFeatures,
            OutputScore: result.RiskScore,
            Confidence: confidence,
            FeatureContributionsJson: contributions,
            RuntimeMs: (int)sw.ElapsedMilliseconds,
            InferenceBackend: "onnx"));
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"prediction logging failed: {ex.Message}");
    }

    return Results.Ok(result);
});

// --- Parity self-test (open): tokenizer parity AND runtime parity, separately ---
app.MapGet("/parity", () =>
{
    if (!File.Exists(referencePath))
        return Results.NotFound(new { error = $"reference not found: {referencePath}" });

    using var doc = JsonDocument.Parse(File.ReadAllText(referencePath));
    var root = doc.RootElement;
    double tol = root.GetProperty("tolerance").GetDouble();

    var results = new List<object>();
    bool allPass = true;

    foreach (var s in root.GetProperty("samples").EnumerateArray())
    {
        string text = s.GetProperty("text").GetString()!;
        long[] refIds = s.GetProperty("input_ids").EnumerateArray().Select(e => e.GetInt64()).ToArray();
        float[] refLogits = s.GetProperty("logits").EnumerateArray().Select(e => e.GetSingle()).ToArray();

        EncodedInput enc = scorer.Encode(text);
        bool idsMatch = enc.InputIds.Length == refIds.Length && enc.InputIds.SequenceEqual(refIds);

        float[] logits = scorer.LogitsFor(enc);
        double maxDiff = idsMatch
            ? logits.Zip(refLogits, (a, b) => Math.Abs(a - b)).DefaultIfEmpty(0).Max()
            : double.NaN;
        bool logitsMatch = idsMatch && maxDiff <= tol;

        bool pass = idsMatch && logitsMatch;
        allPass &= pass;
        results.Add(new
        {
            text = text.Length > 60 ? text[..60] + "..." : text,
            tokenizer_parity = idsMatch,
            runtime_parity = logitsMatch,
            max_logit_diff = double.IsNaN(maxDiff) ? (double?)null : Math.Round(maxDiff, 8),
            diagnosis = pass ? "ok"
                       : !idsMatch ? "TOKENIZER MISMATCH (input_ids differ)"
                       : "RUNTIME MISMATCH (ids ok, logits differ)"
        });
    }

    return Results.Ok(new { all_pass = allPass, tolerance = tol, samples = results });
});

app.Run();