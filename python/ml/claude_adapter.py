from __future__ import annotations
 
import os
 
 
class ClaudeAdapter:
    name = "claude"
 
    def __init__(self, model: str = "claude-sonnet-4-6", api_key: str | None = None):
        import anthropic
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set (env var or api_key arg).")
        self._client = anthropic.Anthropic(api_key=key)
        self._model = model
        self.name = f"claude:{model}"
 
    def complete(self, system: str, user: str, max_tokens: int) -> str:
        msg = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            temperature=0,                      
            system=system,
            messages=[
                {"role": "user", "content": user},
            ],
        )
        text = "".join(block.text for block in msg.content if getattr(block, "type", None) == "text")
        import os as _os
        if _os.environ.get("EXPLAIN_DEBUG"):
            print("=== RAW LLM RESPONSE ===")
            print(repr(text))
            print("=== stop_reason:", msg.stop_reason, "===")
        return _extract_json(text)
 
 
def _extract_json(text: str) -> str:
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
        s = s.strip()
    start = s.find("{")
    if start == -1:
        return s
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return s[start:i + 1]
    return s[start:]