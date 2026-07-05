using Microsoft.AspNetCore.RateLimiting;
using RiskSignalApi.Services;

namespace RiskSignalApi.Middleware;

public sealed class ApiKeyMiddleware
{
    private const string HeaderName = "X-API-Key";
    private static readonly HashSet<string> OpenPaths =
        new(StringComparer.OrdinalIgnoreCase) { "/health", "/parity" };

    private readonly RequestDelegate _next;

    public ApiKeyMiddleware(RequestDelegate next) => _next = next;

    public async Task InvokeAsync(HttpContext ctx, PostgresService pg)
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

        int? keyId = await pg.ValidateApiKeyAsync(provided.ToString(), ctx.RequestAborted);
        if (keyId is null)
        {
            await Reject(ctx, "invalid or inactive API key");
            return;
        }

        ctx.Items["ApiKey"] = keyId.Value;
        await _next(ctx);
    }

    private static async Task Reject(HttpContext ctx, string message)
    {
        ctx.Response.StatusCode = StatusCodes.Status401Unauthorized;
        await ctx.Response.WriteAsJsonAsync(new { error = message });
    }
}