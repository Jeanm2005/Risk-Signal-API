using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using Npgsql;
using RiskSignalApi.Middleware;
using RiskSignalApi.Models;
using RiskSignalApi.Services;

var builder = WebApplication.CreateBuilder(args);

string artifacts = Path.Combine(AppContext.BaseDirectory, "artifacts");
string vocabPath = File.Exists(Path.Combine(artifacts, "vocab.txt"))
    ? Path.Combine(artifacts, "vocab.txt")                       
    : Path.Combine(artifacts, "tokenizer", "vocab.txt");         
var tokenizer = new TokenizerService(vocabPath);
var scorer = new ScoringService(Path.Combine(artifacts, "finbert.onnx"), tokenizer);
string referencePath = Path.Combine(artifacts, "parity_reference.json");

string? connString =
    Environment.GetEnvironmentVariable("RISK_DB_CONNECTION")
    ?? builder.Configuration.GetConnectionString("Postgres");
if (string.IsNullOrWhiteSpace(connString))
    connString = "Host=localhost;Port=5432;Database=risk_signal_db;Username=postgres;Password=postgres";
var dataSource = NpgsqlDataSource.Create(connString);

builder.Services.AddSingleton(tokenizer);
builder.Services.AddSingleton(scorer);
builder.Services.AddSingleton(dataSource);
builder.Services.AddSingleton<PostgresService>();
builder.Services.AddSingleton<RateLimiter>();

var app = builder.Build();

app.UseDefaultFiles();
app.UseStaticFiles();
app.UseMiddleware<ApiKeyMiddleware>();

app.MapPost("/keys/demo", async (HttpContext ctx, PostgresService pg, RateLimiter limiter) =>
{
    string ip = ctx.Request.Headers.TryGetValue("X-Forwarded-For", out var fwd) && fwd.Count > 0
        ? fwd.ToString().Split(',')[0].Trim()
        : ctx.Connection.RemoteIpAddress?.ToString() ?? "unknown";

    var decision = limiter.CheckNamed($"mint:{ip}", limit: 5, window: TimeSpan.FromHours(24),
                                      DateTimeOffset.UtcNow);
    if (!decision.Allowed)
    {
        ctx.Response.Headers["Retry-After"] = decision.RetryAfterSeconds?.ToString() ?? "3600";
        return Results.Json(new { error = "Too many demo keys requested from your network. Try again later." },
                            statusCode: StatusCodes.Status429TooManyRequests);
    }

    var (raw, expiresAt) = await pg.CreateDemoKeyAsync(requestsPerHour: 30, ttl: TimeSpan.FromHours(24));
    return Results.Ok(new
    {
        apiKey = raw,
        expiresAt,
        requestsPerHour = 30,
        note = "Demo key: scoped to /score, ~30 requests/hour, expires in 24h. Store it now."
    });
});

app.MapGet("/health", () => Results.Ok(new { status = "ok" }));

app.MapGet("/alerts", async (PostgresService pg, string? severity, string? ticker, int? limit) =>
{
    int lim = Math.Clamp(limit ?? 50, 1, 200);
    string? sev = string.IsNullOrWhiteSpace(severity) ? null : severity.ToLowerInvariant();
    string? tk = string.IsNullOrWhiteSpace(ticker) ? null : ticker.ToUpperInvariant();
    var alerts = await pg.GetAlertsAsync(sev, tk, lim);
    return Results.Ok(alerts);
});

app.MapGet("/risk/{ticker}", async (PostgresService pg, string ticker) =>
{
    var detail = await pg.GetRiskDetailAsync(ticker.ToUpperInvariant(), headlinesPerAlert: 5);
    return detail is null
        ? Results.NotFound(new { error = $"no company found for ticker '{ticker}'" })
        : Results.Ok(detail);
});

app.MapPost("/score", async (ScoreRequest req, ScoringService svc, PostgresService pg) =>
{
    if (string.IsNullOrWhiteSpace(req.Text))
        return Results.BadRequest(new { error = "text is required" });

    var sw = Stopwatch.StartNew();
    ScoreResult result = svc.Score(req.Text);
    sw.Stop();

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

app.MapFallbackToFile("index.html");

app.Run();