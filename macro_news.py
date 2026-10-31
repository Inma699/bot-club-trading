import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


_BULLISH_TERMS = (
    "adoption",
    "approved",
    "approval",
    "breakout",
    "bullish",
    "gains",
    "inflows",
    "institutional demand",
    "rate cut",
    "rally",
    "rebound",
    "surge",
    "all time high",
    "record high",
    "alcista",
    "aprobacion",
    "adopcion",
    "entradas netas",
    "sube",
    "subida",
)
_BEARISH_TERMS = (
    "ban",
    "bearish",
    "crackdown",
    "crash",
    "decline",
    "drop",
    "falls",
    "hack",
    "hawkish",
    "higher rates",
    "outflows",
    "plunge",
    "rate hike",
    "recession",
    "sell off",
    "slump",
    "tariff",
    "liquidation",
    "bajista",
    "caida",
    "prohibicion",
    "salidas netas",
    "venta masiva",
)


@dataclass(frozen=True)
class MacroHeadlineAnalysis:
    decision: str
    bullish: tuple[str, ...]
    bearish: tuple[str, ...]
    neutral: tuple[str, ...]
    total: int


def _normalize(text: str) -> str:
    without_accents = unicodedata.normalize("NFKD", text)
    ascii_text = without_accents.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()


def _matches_any_term(headline: str, terms: Sequence[str]) -> bool:
    normalized_headline = f" {_normalize(headline)} "
    return any(f" {_normalize(term)} " in normalized_headline for term in terms)


def analyze_macro_headlines(
    news_by_topic: Mapping[str, Sequence[str]],
) -> MacroHeadlineAnalysis:
    unique_headlines = []
    seen = set()
    for headlines in news_by_topic.values():
        for headline in headlines:
            title = str(headline).strip()
            normalized = _normalize(title)
            if title and normalized not in seen:
                unique_headlines.append(title)
                seen.add(normalized)

    bullish = []
    bearish = []
    neutral = []
    for title in unique_headlines:
        is_bullish = _matches_any_term(title, _BULLISH_TERMS)
        is_bearish = _matches_any_term(title, _BEARISH_TERMS)
        if is_bullish and not is_bearish:
            bullish.append(title)
        elif is_bearish and not is_bullish:
            bearish.append(title)
        else:
            neutral.append(title)

    if not unique_headlines:
        decision = "SIN DATOS"
    elif len(bullish) >= len(bearish) + 2:
        decision = "MAYORMENTE ALCISTA"
    elif len(bearish) >= len(bullish) + 2:
        decision = "MAYORMENTE BAJISTA"
    else:
        decision = "EN RANGO / SIN SESGO CLARO"

    return MacroHeadlineAnalysis(
        decision=decision,
        bullish=tuple(bullish),
        bearish=tuple(bearish),
        neutral=tuple(neutral),
        total=len(unique_headlines),
    )


def format_macro_news_summary(
    news_by_topic: Mapping[str, Sequence[str]],
    rss_errors: Sequence[str] = (),
) -> str:
    analysis = analyze_macro_headlines(news_by_topic)
    decision = analysis.decision
    bullish = analysis.bullish
    bearish = analysis.bearish
    neutral = analysis.neutral

    if decision == "SIN DATOS":
        conclusion = (
            "No se puede establecer un sesgo hoy porque Google News RSS no devolvió titulares."
        )
    else:
        conclusion = (
            f"Balance de titulares: {len(bullish)} alcistas, {len(bearish)} bajistas y "
            f"{len(neutral)} mixtos/neutrales."
        )

    lines = [
        "📰 RESUMEN BTC — TITULARES DE GOOGLE NEWS RSS",
        "",
        f"📍 Sesgo orientativo de hoy: {decision}",
        conclusion,
    ]

    if rss_errors:
        lines.append("⚠️ Algunas consultas RSS fallaron; el resumen puede estar incompleto.")

    shown = 0
    seen_in_report = set()
    for topic, headlines in news_by_topic.items():
        unique_topic_headlines = []
        for headline in headlines:
            title = str(headline).strip()
            normalized = _normalize(title)
            if title and normalized not in seen_in_report:
                unique_topic_headlines.append(title)
                seen_in_report.add(normalized)
        if unique_topic_headlines:
            lines.extend(("", f"• {topic}:"))
            for title in unique_topic_headlines[:2]:
                shortened = title if len(title) <= 150 else f"{title[:147].rstrip()}..."
                lines.append(f"  - {shortened}")
                shown += 1

    if shown == 0:
        lines.extend(("", "No hay titulares disponibles; no se asigna dirección al mercado."))
    else:
        lines.extend(
            (
                "",
                "La etiqueta se calcula por palabras clave en los titulares y exige una "
                "diferencia mínima de 2; «en rango» significa que no hay sesgo claro en "
                "las noticias, no que el gráfico esté técnicamente lateral.",
            )
        )

    lines.extend(
        (
            "",
            "Fuente: Google News RSS, sin análisis de IA. Contexto informativo, no consejo "
            "financiero ni señal automática de trading.",
        )
    )
    return "\n".join(lines)
