"""Deterministic text metrics (BACKEND-02).

The LLM proposes keywords; these helpers re-weight them against the actual
transcript (TF-style) and drop anything scoring below MIN_KEYWORD_SCORE, plus
compute reading stats and complexity metrics for the analytics payload.
"""
import re
from collections import Counter

# Unicode-aware word pattern: a leading letter plus letters/digits and
# combining marks. Marks matter: Devanagari vowel signs/virama (U+0900-097F
# block) are non-\w, so plain \w shatters Hindi words into <=2-char fragments
# that the len>2 keyword filter then drops entirely. Indic + Latin diacritic
# ranges below keep such words whole. Pure numbers are not tokens.
_MARKS = ("\u0300-\u036f"  # combining diacriticals
          "\u0900-\u097f\u0980-\u09ff\u0a00-\u0a7f\u0a80-\u0aff"  # Indic scripts
          "\u0b00-\u0b7f\u0b80-\u0bff\u0c00-\u0c7f\u0c80-\u0cff\u0d00-\u0d7f"
          "\u200c\u200d")  # zero-width joiners inside conjuncts
WORD_RE = re.compile(r"[^\W\d_][\w" + _MARKS + r"]*(?:'[\w]+)?", re.UNICODE)
SENTENCE_RE = re.compile(r"[^.!?।]+[.!?।]")
MIN_KEYWORD_SCORE = 0.15

STOPWORDS = frozenset(
    "a an the and or but if then else when while of at by for with about into "
    "through during to from in on out over under again further once here there "
    "all any both each few more most other some such no nor not only own same "
    "so than too very can will just don should now is are was were be been "
    "being have has had having do does did doing would could ought i you he "
    "she it we they them his her its our your their this that these those as "
    # high-frequency Hindi function words (Devanagari transcripts)
    "ke ki ka ko se ne par hai hain tha the thi ye vo ye yehi vahi jo so "
    "aur lekin kyonki jab tab abhi bhi nahi nahin kya kaise jaise vaise "
    "mein main hum tum aap yah vah ise use inhe unhe iska uska apna apni "
    "apne karte karta karti karna hoga honge hota hote hoti gaya gayi gaye "
    "kiya kiya gaya liye taraf jaisa doston aaj bahut zyada thoda sab kuch "
    "koi koi bhi".split()
)


def tokenize(text):
    """Lowercase word tokens for scoring (keeps contractions, Unicode-aware)."""
    return WORD_RE.findall((text or "").lower())


def compute_stats(full_text, top_keywords=()):
    """Reading stats: word count, reading minutes, WPM, top keyword terms."""
    words = tokenize(full_text)
    word_count = len(words)
    wpm = 200
    reading_minutes = max(1, round(word_count / wpm)) if word_count else 0
    return {
        "word_count": word_count,
        "reading_minutes": reading_minutes,
        "avg_words_per_min": round(word_count / reading_minutes) if reading_minutes else 0,
        "top_keywords": list(top_keywords)[:5],
    }


def complexity_metrics(full_text):
    """Lexical complexity signals (inputs for CHARTS-01). All ratios in 0..1."""
    words = tokenize(full_text)
    if not words:
        return {"type_token_ratio": 0.0, "avg_words_per_sentence": 0.0, "long_word_ratio": 0.0}
    sentences = [s for s in SENTENCE_RE.findall(full_text or "") if s.strip()] or [full_text]
    long_words = sum(1 for w in words if len(w) > 6)
    return {
        "type_token_ratio": round(len(set(words)) / len(words), 3),
        "avg_words_per_sentence": round(len(words) / len(sentences), 1),
        "long_word_ratio": round(long_words / len(words), 3),
    }


def rescore_keywords(llm_keywords, full_text, min_score=MIN_KEYWORD_SCORE):
    """Re-weight LLM keyword scores by observed transcript frequency.

    combined = 0.6 * llm_score + 0.4 * min(1, count / max_count).
    Returns [{term, score, count}] sorted desc, dropping score < min_score.
    """
    words = tokenize(full_text)
    total = len(words) or 1
    counts = Counter(words)
    scored = []
    for kw in llm_keywords or []:
        term = " ".join(str(kw.get("term", "")).split()).lower()
        if not term:
            continue
        try:
            llm_score = float(kw.get("score", 0))
        except (TypeError, ValueError):
            llm_score = 0.0
        parts = term.split()
        if len(parts) == 1:
            count = counts.get(term, 0)
        else:
            count = sum(
                1 for i in range(max(0, len(words) - len(parts) + 1))
                if words[i : i + len(parts)] == parts
            )
        tf_boost = min(1.0, (count / total) * 50)
        combined = round(0.6 * max(0.0, min(1.0, llm_score)) + 0.4 * tf_boost, 3)
        if combined >= min_score and count > 0:
            scored.append({"term": term, "score": combined, "count": count})
    scored.sort(key=lambda k: (-k["score"], -k["count"], k["term"]))
    return scored


def top_terms(full_text, n=10):
    """Fallback keyword mining: most frequent non-stopwords (for degraded mode)."""
    counts = Counter(w for w in tokenize(full_text) if w not in STOPWORDS and len(w) > 2)
    return [{"term": t, "score": round(c / (counts.most_common(1)[0][1] or 1), 3), "count": c}
            for t, c in counts.most_common(n)]
