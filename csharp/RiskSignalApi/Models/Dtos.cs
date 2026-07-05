namespace RiskSignalApi.Models;

public sealed record ScoreRequest(string Text);

public sealed record ScoreResult(
    string Label,
    IReadOnlyDictionary<string, float> Scores,
    float[] Logits,
    float RiskScore,
    int TokenCount);

/// <summary>Shape of one prediction_logs row (see PostgresService.LogPredictionAsync for the mapping).</summary>
public sealed record PredictionLog(
    string ModelVersion,
    string InputFeaturesJson,
    double OutputScore,
    double Confidence,
    string FeatureContributionsJson,
    int RuntimeMs,
    string InferenceBackend);