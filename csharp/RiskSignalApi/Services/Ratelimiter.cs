using System.Collections.Concurrent;

namespace RiskSignalApi.Services;

public sealed class RateLimiter
{
    private static readonly TimeSpan Window = TimeSpan.FromHours(1);

    private readonly ConcurrentDictionary<int, Queue<DateTimeOffset>> _hits = new();

    private readonly ConcurrentDictionary<string, Queue<DateTimeOffset>> _named = new();

    public readonly record struct Decision(bool Allowed, int? RetryAfterSeconds);

    public Decision Check(int keyId, int? requestsPerHour, DateTimeOffset now)
    {
        if (requestsPerHour is not int limit || limit <= 0)
            return new Decision(true, null);   

        var q = _hits.GetOrAdd(keyId, _ => new Queue<DateTimeOffset>());
        lock (q)
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

    public Decision CheckNamed(string key, int limit, TimeSpan window, DateTimeOffset now)
    {
        if (limit <= 0)
            return new Decision(true, null);

        var q = _named.GetOrAdd(key, _ => new Queue<DateTimeOffset>());
        lock (q)
        {
            DateTimeOffset cutoff = now - window;
            while (q.Count > 0 && q.Peek() <= cutoff)
                q.Dequeue();

            if (q.Count >= limit)
            {
                DateTimeOffset oldest = q.Peek();
                int retry = (int)Math.Ceiling((oldest + window - now).TotalSeconds);
                return new Decision(false, Math.Max(retry, 1));
            }

            q.Enqueue(now);
            return new Decision(true, null);
        }
    }
}