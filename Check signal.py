import os
import json
import time
import requests

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
NTFY_TOPIC = os.environ["NTFY_TOPIC"]

COINS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

STATE_FILE = "state.json"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_signal(coin):
    prompt = f"""You are a crypto news-sentiment analyst. Research the LATEST news (last 24-48 hours) about "{coin}" cryptocurrency using web search.

Respond with ONLY a raw JSON object (no markdown fences, no preamble):
{{
  "signal": "BUY" | "SELL" | "HOLD",
  "score": <integer -100 to 100>,
  "confidence": <integer 0-100>,
  "reasoning": "<2-3 sentence summary in simple English of why>"
}}"""

    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": "claude-sonnet-4-6",
            "max_tokens": 500,
            "messages": [{"role": "user", "content": prompt}],
            "tools": [{"type": "web_search_20250305", "name": "web_search"}],
        },
        timeout=90,
    )
    response.raise_for_status()
    data = response.json()

    text_blocks = [b["text"] for b in data.get("content", []) if b.get("type") == "text"]
    full_text = "\n".join(text_blocks).strip()
    cleaned = full_text.replace("```json", "").replace("```", "").strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON found in response for {coin}: {full_text[:200]}")

    return json.loads(cleaned[start:end + 1])


def send_ntfy(coin, old_signal, new_signal, reasoning, confidence):
    title = f"{coin}: {old_signal or 'NEW'} -> {new_signal}"
    priority = "urgent" if new_signal in ("BUY", "SELL") else "default"
    tags = "rocket" if new_signal == "BUY" else "chart_with_downwards_trend" if new_signal == "SELL" else "eyes"

    requests.post(
        f"https://ntfy.sh/{NTFY_TOPIC}",
        data=f"{reasoning}\n\nConfidence: {confidence}%".encode("utf-8"),
        headers={
            "Title": title,
            "Priority": priority,
            "Tags": tags,
        },
        timeout=15,
    )


def main():
    state = load_state()
    changed = False

    for coin in COINS:
        try:
            result = get_signal(coin)
            new_signal = result["signal"]
            old_signal = state.get(coin, {}).get("signal")

            print(f"{coin}: old={old_signal} new={new_signal} confidence={result.get('confidence')}")

            # Notify only if this is not the very first run AND signal changed
            if old_signal is not None and old_signal != new_signal:
                send_ntfy(coin, old_signal, new_signal, result.get("reasoning", ""), result.get("confidence", 0))
                print(f"  -> notification sent for {coin}")

            state[coin] = {
                "signal": new_signal,
                "score": result.get("score"),
                "confidence": result.get("confidence"),
                "reasoning": result.get("reasoning"),
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            }
            changed = True

        except Exception as e:
            print(f"Error checking {coin}: {e}")

    if changed:
        save_state(state)


if __name__ == "__main__":
    main()
