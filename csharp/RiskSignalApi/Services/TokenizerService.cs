using Microsoft.ML.Tokenizers;

namespace RiskSignalApi.Services;

/// <summary>
/// Reproduces ProsusAI/finbert's tokenization (bert-base-uncased WordPiece) so the
/// input_ids fed to ONNX match what HuggingFace produced. This is the single most
/// failure-prone part of the serving layer: if these ids drift from the golden
/// reference, every score is quietly wrong.
///
/// We use BertTokenizer's DEFAULT options, which the library models on HF's
/// bert-base implementation (lowercasing + accent stripping on by default). The
/// /parity endpoint verifies this empirically against the golden reference -- if
/// tokenizer_parity is false there, we set explicit options for this exact package
/// version rather than guessing property names blind.
/// </summary>
public sealed class TokenizerService
{
    private readonly BertTokenizer _tokenizer;

    public TokenizerService(string vocabPath)
    {
        if (!File.Exists(vocabPath))
            throw new FileNotFoundException($"vocab.txt not found at {vocabPath}", vocabPath);

        _tokenizer = BertTokenizer.Create(vocabPath);
    }

    /// <summary>
    /// Encode text into the three int64 tensors ONNX expects. EncodeToIds adds
    /// [CLS] ... [SEP]; token_type_ids are all zeros for single-sequence input.
    /// Caps at maxLength (512) with truncation that preserves [CLS]/[SEP].
    /// </summary>
    public EncodedInput Encode(string text, int maxLength = 512)
    {
        IReadOnlyList<int> ids = _tokenizer.EncodeToIds(text);

        if (ids.Count > maxLength)
        {
            var truncated = new List<int>(maxLength);
            truncated.Add(ids[0]);                                  // [CLS]
            for (int i = 1; i < maxLength - 1; i++) truncated.Add(ids[i]);
            truncated.Add(ids[^1]);                                 // [SEP]
            ids = truncated;
        }

        int n = ids.Count;
        var inputIds = new long[n];
        var attentionMask = new long[n];
        var tokenTypeIds = new long[n];
        for (int i = 0; i < n; i++)
        {
            inputIds[i] = ids[i];
            attentionMask[i] = 1;
            tokenTypeIds[i] = 0;
        }
        return new EncodedInput(inputIds, attentionMask, tokenTypeIds);
    }
}

public readonly record struct EncodedInput(long[] InputIds, long[] AttentionMask, long[] TokenTypeIds);