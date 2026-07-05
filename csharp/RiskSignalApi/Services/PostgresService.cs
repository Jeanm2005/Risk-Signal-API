using System.Security.Cryptography;
using System.Text;
using Npgsql;
using NpgsqlTypes;
using RiskSignalApi.Models;

namespace RiskSignalApi.Services;

/// <summary>
/// Postgres access for auth and prediction logging. Uses Npgsql directly (no ORM):
/// two queries and an insert don't justify EF Core's ceremony, and raw SQL keeps the
/// data flow explicit.
/// </summary>
public sealed class PostgresService
{
    private readonly NpgsqlDataSource _db;

    public PostgresService(NpgsqlDataSource db) => _db = db;

    /// <summary>
    /// Validate an incoming API key. We store only the SHA-256 of each key (never the
    /// raw value), so a leaked database yields no usable keys. The UPDATE ... RETURNING
    /// both authenticates and stamps last_used_at in a single round-trip; a null result
    /// means no active key matched.
    /// </summary>
    public async Task<int?> ValidateApiKeyAsync(string rawKey, CancellationToken ct = default)
    {
        string hash = HashKey(rawKey);
        await using var cmd = _db.CreateCommand(
            "UPDATE api_keys SET last_used_at = now() " +
            "WHERE key_hash = @h AND active = true RETURNING id");
        cmd.Parameters.AddWithValue("h", hash);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        return await reader.ReadAsync(ct) ? reader.GetInt32(0) : null;
    }

    /// <summary>
    /// Log one prediction. The prediction_logs table was designed for company risk
    /// scoring, so we map an ad-hoc /score call onto it honestly:
    ///   company_id            -> NULL (not tied to a company)
    ///   model_version         -> 'finbert-base'
    ///   inference_backend     -> 'onnx'
    ///   input_features (jsonb)-> {"text_sha256": ..., "token_count": N}  (hash, not raw text)
    ///   output_score          -> negative probability (the risk axis)
    ///   confidence            -> max class probability
    ///   feature_contributions -> {positive, negative, neutral}
    /// </summary>
    public async Task LogPredictionAsync(PredictionLog log, CancellationToken ct = default)
    {
        await using var cmd = _db.CreateCommand(
            "INSERT INTO prediction_logs " +
            "(model_version, input_features, output_score, confidence, " +
            " feature_contributions, runtime_ms, inference_backend) " +
            "VALUES ($1, $2, $3, $4, $5, $6, $7)");
        // Positional ($N) params, added strictly in order -- no name-matching to misfire.
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.ModelVersion });
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Jsonb, Value = log.InputFeaturesJson });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.OutputScore });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.Confidence });
        cmd.Parameters.Add(new NpgsqlParameter { NpgsqlDbType = NpgsqlDbType.Jsonb, Value = log.FeatureContributionsJson });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.RuntimeMs });
        cmd.Parameters.Add(new NpgsqlParameter { Value = log.InferenceBackend });
        await cmd.ExecuteNonQueryAsync(ct);
    }

    /// <summary>SHA-256 hex (lowercase, 64 chars) -- matches api_keys.key_hash and the Python key-gen.</summary>
    public static string HashKey(string raw) =>
        Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(raw)));
}