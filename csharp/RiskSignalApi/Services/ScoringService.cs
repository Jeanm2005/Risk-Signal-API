using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using RiskSignalApi.Models;

namespace RiskSignalApi.Services;

/// <summary>
/// Runs finbert.onnx via ONNX Runtime and turns logits into labeled probabilities.
/// Label order is the export contract: 0=positive, 1=negative, 2=neutral. Softmax is
/// applied here (the graph outputs raw logits), matching the Python side.
/// </summary>
public sealed class ScoringService : IDisposable
{
    // MUST match model.config.id2label from the export. Do not reorder.
    private static readonly string[] Labels = { "positive", "negative", "neutral" };

    private readonly InferenceSession _session;
    private readonly TokenizerService _tokenizer;

    public ScoringService(string onnxPath, TokenizerService tokenizer)
    {
        if (!File.Exists(onnxPath))
            throw new FileNotFoundException($"finbert.onnx not found at {onnxPath}", onnxPath);
        _session = new InferenceSession(onnxPath);
        _tokenizer = tokenizer;
    }

    /// <summary>Tokenize + run the model. Returns logits and softmax probabilities.</summary>
    public ScoreResult Score(string text)
    {
        EncodedInput enc = _tokenizer.Encode(text);
        float[] logits = RunModel(enc);
        float[] probs = Softmax(logits);

        var byLabel = new Dictionary<string, float>(Labels.Length);
        for (int i = 0; i < Labels.Length; i++) byLabel[Labels[i]] = probs[i];

        int argmax = 0;
        for (int i = 1; i < probs.Length; i++) if (probs[i] > probs[argmax]) argmax = i;

        // Positional construction: Label, Scores, Logits, RiskScore.
        // RiskScore = negative probability, matching the Python pipeline's risk axis.
        return new ScoreResult(Labels[argmax], byLabel, logits, byLabel["negative"], enc.InputIds.Length);
    }

    /// <summary>Expose raw logits for the parity test (compare against golden reference).</summary>
    public float[] LogitsFor(EncodedInput enc) => RunModel(enc);

    public EncodedInput Encode(string text) => _tokenizer.Encode(text);

    private float[] RunModel(EncodedInput enc)
    {
        int seq = enc.InputIds.Length;
        var dims = new[] { 1, seq };

        var inputs = new List<NamedOnnxValue>
        {
            NamedOnnxValue.CreateFromTensor("input_ids",
                new DenseTensor<long>(enc.InputIds, dims)),
            NamedOnnxValue.CreateFromTensor("attention_mask",
                new DenseTensor<long>(enc.AttentionMask, dims)),
            NamedOnnxValue.CreateFromTensor("token_type_ids",
                new DenseTensor<long>(enc.TokenTypeIds, dims)),
        };

        using IDisposableReadOnlyCollection<DisposableNamedOnnxValue> results = _session.Run(inputs);
        // Output "logits" shape [1, 3]
        return results.First(v => v.Name == "logits").AsEnumerable<float>().ToArray();
    }

    private static float[] Softmax(float[] logits)
    {
        float max = logits.Max();
        double sum = 0;
        var exp = new double[logits.Length];
        for (int i = 0; i < logits.Length; i++) { exp[i] = Math.Exp(logits[i] - max); sum += exp[i]; }
        var probs = new float[logits.Length];
        for (int i = 0; i < logits.Length; i++) probs[i] = (float)(exp[i] / sum);
        return probs;
    }

    public void Dispose() => _session.Dispose();
}