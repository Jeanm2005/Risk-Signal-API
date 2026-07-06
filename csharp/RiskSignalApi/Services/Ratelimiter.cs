using System.Collections.Concurrent;

namespace RiskSignalApi.Services;

public sealed class RateLimiter
{
    private static readonly TimeSpan Window = TimeSpan.FromHours(1);

    private readonly ConcurrentDictionary<int, Queue<DateTimeOffset>> _hits = new();

    public readonly record struct Decision(bool Allowed, int? RetryAfterSeconds);

    public Decision Check(int keyId, int? requestPerHour, DateTimeOffset now)
    {
        if (requestPerHour is not int limit || limit <= 0)
            return new Decision(true, null);

        var q = _hits.GetOrAdd(keyId, _ => new Queue<DateTimeOffset>());
        lock(q)
        {
            DateTimeOffset cutoff = now - Window;
            while (q.Count > 0 && q.Peek() <= cutoff)
                q.Dequeue();

            if (q.Count >= limit)
            {
                DateTimeOffset oldest = q.Peek();
                int retry = (int)Math.Ceiling((oldest + Window - now).TotalSeconds);
                return new Decision(false, Math.Max(retry, 1));
            }

            q.Enqueue(now);
            return new Decision(true, null);
        }
    }
}