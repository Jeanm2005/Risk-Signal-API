using RiskSignalApi.Services;
using RiskSignalApi.Models;

namespace RiskSignalApi.Middleware;

public sealed class ApiKeyMiddleware
{
    private const string HeaderName = "X-API-Key";
    private static readonly HashSet<string> OpenPaths =
        new(StringComparer.OrdinalIgnoreCase) { "/health", "/parity" };

    private readonly RequestDelegate _next;

    public ApiKeyMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext ctx, PostgresService pg, RateLimiter limiter)
    {
        string path = ctx.Request.Path.Value ?? string.Empty;
        if (OpenPaths.Contains(path))
        {
            await _next(ctx);
            return;
        }

        if (!ctx.Request.Headers.TryGetValue(HeaderName, out var provided) ||
            string.IsNullOrWhiteSpace(provided))
        {
            await Reject(ctx, "missing X-API-Key header");
            return;
        }

        ApiKeyInfo? key = await pg.ValidateApiKeyAsync(provided.ToString(), ctx.RequestAborted);
        if (key is null)
        {
            await Reject(ctx, "invalid or inactive API key");
            return;
        }

        RateLimiter.Decision d = limiter.Check(key.Id, key.RequestsPerHour, DateTimeOffset.UtcNow);
        if (!d.Allowed)
        {
            if (d.RetryAfterSeconds is int secs)
                ctx.Response.Headers.RetryAfter = secs.ToString();
            ctx.Response.StatusCode = StatusCodes.Status429TooManyRequests;
            await ctx.Response.WriteAsJsonAsync(new
            {
                error = "rate limit exceeded",
                retry_after_seconds = d.RetryAfterSeconds
            });
            return;
        }

        ctx.Items["ApiKeyId"] = key.Id;   
        await _next(ctx);
    }

    private static async Task Reject(HttpContext ctx, string message)
    {
        ctx.Response.StatusCode = StatusCodes.Status401Unauthorized;
        await ctx.Response.WriteAsJsonAsync(new { error = message });
    }
}