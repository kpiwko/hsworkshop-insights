import json
import re
from collections import Counter
from typing import Any

# Common stop words — English + Czech
_STOP_WORDS: set[str] = {
    # English
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "being", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "shall", "can", "need", "dare",
    "ought", "used", "it", "its", "i", "you", "he", "she", "we", "they",
    "me", "him", "her", "us", "them", "my", "your", "his", "our", "their",
    "this", "that", "these", "those", "what", "which", "who", "whom",
    "when", "where", "why", "how", "all", "both", "each", "few", "more",
    "most", "other", "some", "such", "no", "not", "only", "same", "so",
    "than", "too", "very", "just", "as", "if", "about", "up", "out",
    "into", "then", "there", "also", "like", "get", "make", "know",
    "think", "want", "use", "go", "see", "come", "take", "give",
    # Czech
    "a", "ale", "ani", "ano", "at", "az", "byl", "byla", "bylo", "být",
    "co", "či", "do", "ho", "i", "já", "je", "jeho", "jej", "jejich",
    "její", "jen", "její", "ještě", "ji", "jí", "jich", "jinak", "již",
    "jsem", "jsi", "jsou", "jak", "jako", "kde", "kdo", "když", "k",
    "ke", "která", "které", "který", "která", "mi", "mu", "my", "na",
    "nad", "ne", "nebo", "něco", "no", "o", "od", "on", "ona", "oni",
    "ono", "po", "pod", "pro", "před", "při", "se", "si", "s", "tak",
    "také", "takže", "tam", "te", "ten", "toto", "tu", "ty", "už",
    "v", "ve", "vše", "všechno", "z", "za", "ze", "že",
}

_TOKEN_RE = re.compile(r"[a-záčďéěíňóřšťúůýžA-ZÁČĎÉĚÍŇÓŘŠŤÚŮÝŽ]{3,}", re.UNICODE)


def _extract_user_messages(input_json: str) -> list[str]:
    """Parse input JSON, return user message contents.

    Handles two formats:
    - Observations (GENERATION): JSON array [{role, content}, ...]
    - Blocked traces: {"user_message": "..."} dict set by guardrails proxy
    """
    try:
        data = json.loads(input_json)
    except Exception:
        return []
    # Blocked trace format: {"user_message": "..."}
    if isinstance(data, dict):
        msg = data.get("user_message", "")
        # Skip OpenWebUI's auto-generated follow-up suggestion prompts
        if not msg or "Suggest 3-5 relevant follow-up" in msg or "### Task:" in msg:
            return []
        return [msg]
    if not isinstance(data, list):
        return []
    return [
        m["content"]
        for m in data
        if isinstance(m, dict)
        and m.get("role") == "user"
        and isinstance(m.get("content"), str)
        # Skip OpenWebUI's auto-generated follow-up suggestion prompt
        and "Suggest 3-5 relevant follow-up" not in m["content"]
        and "### Task:" not in m["content"]
    ]


def _tokenize(text: str) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    return [t for t in tokens if t not in _STOP_WORDS]


def compute_word_frequencies(generations: list[dict[str, Any]]) -> list[dict]:
    """Return [{word, count}] sorted by count descending."""
    counter: Counter = Counter()
    for gen in generations:
        for msg in _extract_user_messages(gen.get("input") or ""):
            counter.update(_tokenize(msg))
    return [{"word": w, "count": c} for w, c in counter.most_common(150)]


def compute_word_graph(generations: list[dict[str, Any]], top_n: int = 60) -> dict:
    """
    Return {nodes: [{id, word, count}], edges: [{source, target, weight}]}.
    Edges connect words that appear together in the same message.
    """
    counter: Counter = Counter()
    co: Counter = Counter()

    for gen in generations:
        for msg in _extract_user_messages(gen.get("input") or ""):
            tokens = list(dict.fromkeys(_tokenize(msg)))  # dedupe, preserve order
            counter.update(tokens)
            for i, a in enumerate(tokens):
                for b in tokens[i + 1:i + 6]:  # window of 5
                    pair = (min(a, b), max(a, b))
                    co[pair] += 1

    top_words = {w for w, _ in counter.most_common(top_n)}
    nodes = [
        {"id": w, "word": w, "count": c}
        for w, c in counter.most_common(top_n)
    ]
    edges = [
        {"source": a, "target": b, "weight": w}
        for (a, b), w in co.most_common(200)
        if a in top_words and b in top_words
    ]
    return {"nodes": nodes, "edges": edges}
