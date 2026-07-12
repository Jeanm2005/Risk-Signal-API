using System.Security.Cryptography;
using System.Text;
using Npgsql;
using NpgsqlTypes;
using RiskSignalApi.Models;

namespace RiskSignalApi.Services;

public sealed class PostgresService
{
    private readonly NpgsqlDataSource _db;

    public PostgresService(NpgsqlDataSource db) => _db = db;

    public async Task<ApiKeyInfo?> ValidateApiKeyAsync(string rawKey, CancellationToken ct = default)
    {
        string hash = HashKey(rawKey);
        await using var cmd = _db.CreateCommand(
            "UPDATE api_keys SET last_used_at = now() " +
            "WHERE key_hash = @h AND active = true " +
            "  AND (expires_at IS NULL OR expires_at > now()) " +   
            "RETURNING id, requests_per_hour");
        cmd.Parameters.AddWithValue("h", hash);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        if (!await reader.ReadAsync(ct))
            return null;
        int id = reader.GetInt32(0);
        int? perHour = reader.IsDBNull(1) ? null : reader.GetInt32(1);
        return new ApiKeyInfo(id, perHour);
    }

    public async Task LogPredictionAsync(PredictionLog log, CancellationToken ct = default)
    {
        await using var cmd = _db.CreateCommand(
            "INSERT INTO prediction_logs " +
            "(model_version, input_features, output_score, confidence, " +
            " feature_contributions, runtime_ms, inference_backend) " +
            "VALUES ($1, $2, $3, $4, $5, $6, $7)");
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.ModelVersion });
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Jsonb, Value = log.InputFeaturesJson });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.OutputScore });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.Confidence });
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Jsonb, Value = log.FeatureContributionsJson });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.RuntimeMs });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.InferenceBackend });
        await cmd.ExecuteNonQueryAsync(ct);
    }

    public static string HashKey(string raw) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(raw)));

    public async Task<(string RawKey, DateTimeOffset ExpiresAt)> CreateDemoKeyAsync(
        int requestsPerHour, TimeSpan ttl, CancellationToken ct = default)
    {
        string raw = "rsk_" + Convert.ToBase64String(RandomNumberGenerator.GetBytes(32))
            .Replace("+", "-").Replace("/", "_").TrimEnd('=');
        string hash = HashKey(raw);
        var expiresAt = DateTimeOffset.UtcNow + ttl;

        await using var cmd = _db.CreateCommand(
            "INSERT INTO api_keys (key_hash, owner, requests_per_hour, active, expires_at) " +
            "VALUES (@h, 'public-demo', @r, true, @e)");
        cmd.Parameters.AddWithValue("h", hash);
        cmd.Parameters.AddWithValue("r", requestsPerHour);
        cmd.Parameters.AddWithValue("e", expiresAt);
        await cmd.ExecuteNonQueryAsync(ct);
        return (raw, expiresAt);
    }

    public async Task<IReadOnlyList<AlertDto>> GetAlertsAsync(
        string? severity, string? ticker, int limit, CancellationToken ct = default)
    {
        await using var cmd = _db.CreateCommand(
            "SELECT a.id, c.ticker, c.name, a.triggered_at, a.severity, a.explanation " +
            "FROM alerts a JOIN companies c ON c.id = a.company_id " +
            "WHERE a.alert_type = 'news_market_anomaly' " +
            "  AND ($1 IS NULL OR a.severity = $1) " +
            "  AND ($2 IS NULL OR c.ticker = $2) " +
            "ORDER BY CASE a.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, " +
            "         a.triggered_at DESC " +
            "LIMIT $3");
        cmd.Parameters.Add(new NpgsqlParameter
            { NpgsqlDbType = NpgsqlDbType.Varchar, Value = (object?)severity ?? DBNull.Value });
        cmd.Parameters.Add(new NpgsqlParameter
            { NpgsqlDbType = NpgsqlDbType.Varchar, Value = (object?)ticker ?? DBNull.Value });
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Integer, Value = limit });

        var rows = new List<AlertDto>();
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
        {
            rows.Add(new AlertDto(
                reader.GetInt32(0),
                reader.GetString(1),
                reader.IsDBNull(2) ? "" : reader.GetString(2),
                reader.GetFieldValue<DateTimeOffset>(3),
                reader.IsDBNull(4) ? "" : reader.GetString(4),
                reader.IsDBNull(5) ? "" : reader.GetString(5)));
        }
        return rows;
    }

    public async Task<RiskDetailDto?> GetRiskDetailAsync(
        string ticker, int headlinesPerAlert, CancellationToken ct = default)
    {
        int companyId;
        string companyName;
        await using (var cc = _db.CreateCommand("SELECT id, name FROM companies WHERE ticker = $1"))
        {
            cc.Parameters.Add(new NpgsqlParameter { Value = ticker });
            await using var cr = await cc.ExecuteReaderAsync(ct);
            if (!await cr.ReadAsync(ct))
                return null;                                   
            companyId = cr.GetInt32(0);
            companyName = cr.IsDBNull(1) ? "" : cr.GetString(1);
        }

        var alerts = new List<(int Id, DateTimeOffset At, string Sev, string Expl)>();
        await using (var ac = _db.CreateCommand(
            "SELECT id, triggered_at, severity, explanation FROM alerts " +
            "WHERE company_id = $1 AND alert_type = 'news_market_anomaly' " +
            "ORDER BY triggered_at DESC"))
        {
            ac.Parameters.Add(new NpgsqlParameter { Value = companyId });
            await using var ar = await ac.ExecuteReaderAsync(ct);
            while (await ar.ReadAsync(ct))
                alerts.Add((ar.GetInt32(0), ar.GetFieldValue<DateTimeOffset>(1),
                            ar.IsDBNull(2) ? "" : ar.GetString(2),
                            ar.IsDBNull(3) ? "" : ar.GetString(3)));
        }

        var result = new List<RiskAlertDto>(alerts.Count);
        foreach (var al in alerts)
        {
            var headlines = new List<HeadlineDto>();
            await using var hc = _db.CreateCommand(
                "SELECT n.id, n.headline, n.url, n.source, n.published_at, n.sentiment_label, n.sentiment_score " +
                "FROM news_articles n " +
                "JOIN article_companies ac ON ac.article_id = n.id " +
                "WHERE ac.company_id = $1 " +
                "  AND n.published_at::date = $2::date " +
                "ORDER BY n.sentiment_score DESC NULLS LAST " +
                "LIMIT $3");
            hc.Parameters.Add(new NpgsqlParameter { Value = companyId });
            hc.Parameters.Add(new NpgsqlParameter { Value = al.At });
            hc.Parameters.Add(new NpgsqlParameter { Value = headlinesPerAlert });
            await using var hr = await hc.ExecuteReaderAsync(ct);
            while (await hr.ReadAsync(ct))
            {
                headlines.Add(new HeadlineDto(
                    hr.GetInt32(0),
                    hr.GetString(1),
                    hr.GetString(2),                                  
                    hr.IsDBNull(3) ? null : hr.GetString(3),
                    hr.IsDBNull(4) ? null : hr.GetFieldValue<DateTimeOffset>(4),
                    hr.IsDBNull(5) ? null : hr.GetString(5),
                    hr.IsDBNull(6) ? null : hr.GetDouble(6)));
            }
            string? narrative = null, llmStatus = null;
            IReadOnlyList<int>? citedIds = null;
            await using (var ec = _db.CreateCommand(
                "SELECT status, narrative, cited_ids FROM alert_explanations WHERE alert_id = $1"))
            {
                ec.Parameters.Add(new NpgsqlParameter { Value = al.Id });
                await using var er = await ec.ExecuteReaderAsync(ct);
                if (await er.ReadAsync(ct))
                {
                    llmStatus = er.IsDBNull(0) ? null : er.GetString(0);
                    narrative = er.IsDBNull(1) ? null : er.GetString(1);
                    if (!er.IsDBNull(2))
                        citedIds = (int[])er.GetValue(2);
                }
            }

            result.Add(new RiskAlertDto(al.Id, al.At, al.Sev, al.Expl, headlines,
                                        narrative, llmStatus, citedIds));
        }

        return new RiskDetailDto(ticker, companyName, result.Count, result);
    }
}