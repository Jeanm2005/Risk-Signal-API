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
            "WHERE key_hash = @h AND active = true RETURNING id, requests_per_hour");
        cmd.Parameters.AddWithValue("h", hash);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        if (!await reader.ReadAsync(ct))
            return null;
        int id = reader.GetInt32(0);
        // requests_per_hour is nullable in the schema; treat NULL as "no limit".
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
}