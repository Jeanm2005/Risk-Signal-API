namespace RiskSignalApi.Models;

public sealed record ScoreRequest(string Text);

public sealed record ScoreResult(
    string Label,
    IReadOnlyDictionary<string, float> Scores,
    float[] Logits,
    float RiskScore,
    int TokenCount);

public sealed record PredictionLog(
    string ModelVersion,
    string InputFeaturesJson,
    double OutputScore,
    double Confidence,
    string FeatureContributionsJson,
    int RuntimeMs,
    string InferenceBackend);

public sealed record ApiKeyInfo(int Id, int? RequestsPerHour);

public sealed record AlertDto(
    int Id,
    string Ticker,
    string CompanyName,
    DateTimeOffset TriggeredAt,
    string Severity,
    string Explanation);

public sealed record HeadlineDto(
    int ArticleId,
    string Headline,
    string Url,
    string? Source,
    DateTimeOffset? PublishedAt,
    string? SentimentLabel,
    double? SentimentScore);

public sealed record RiskAlertDto(
    int Id,
    DateTimeOffset TriggeredAt,
    string Severity,
    string Explanation,
    IReadOnlyList<HeadlineDto> Headlines,
    string? LlmNarrative,
    string? LlmStatus,
    IReadOnlyList<int>? LlmCitedIds);

public sealed record RiskDetailDto(
    string Ticker,
    string CompanyName,
    int AlertCount,
    IReadOnlyList<RiskAlertDto> Alerts);