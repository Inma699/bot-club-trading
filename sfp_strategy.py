from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Sequence


@dataclass(frozen=True)
class DailyLevels:
    day: date
    high: float
    low: float


@dataclass
class SFPReclaimDetector:
    support_swept: bool = False
    resistance_swept: bool = False

    def reset(self) -> None:
        self.support_swept = False
        self.resistance_swept = False

    def update(self, price: float, levels: DailyLevels, deviation: float) -> str | None:
        if not isfinite(price) or price <= 0:
            raise ValueError("El precio debe ser un número positivo y finito.")
        if not 0 < deviation < 1:
            raise ValueError("La desviación debe ser una fracción entre 0 y 1.")
        if (
            not isfinite(levels.low)
            or not isfinite(levels.high)
            or levels.low <= 0
            or levels.high <= levels.low
        ):
            raise ValueError("Los niveles diarios no son válidos.")

        if price <= levels.low * (1 - deviation):
            self.support_swept = True
        if price >= levels.high * (1 + deviation):
            self.resistance_swept = True

        if self.support_swept and price >= levels.low:
            self.reset()
            return "COMPRA"
        if self.resistance_swept and price <= levels.high:
            self.reset()
            return "VENTA"
        return None


def previous_day_levels(
    candles: Sequence[Sequence[float]],
    now: datetime | None = None,
) -> DailyLevels:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("La fecha/hora debe incluir zona horaria.")

    today = now.astimezone(timezone.utc).date()
    previous_day = today - timedelta(days=1)
    previous_day_start = datetime.combine(previous_day, time.min, tzinfo=timezone.utc)
    expected_timestamp = int(previous_day_start.timestamp() * 1000)
    candle = next(
        (row for row in candles if len(row) >= 5 and int(row[0]) == expected_timestamp),
        None,
    )
    if candle is None:
        raise ValueError("Bitget no devolvió la vela UTC completa del día anterior.")

    high = float(candle[2])
    low = float(candle[3])
    if not isfinite(high) or not isfinite(low) or low <= 0 or high <= low:
        raise ValueError("La vela diaria anterior contiene niveles inválidos.")
    return DailyLevels(day=today, high=high, low=low)


def calculate_exit_prices(
    direction: str,
    entry_price: float,
    leverage: int,
    stop_roe_percent: float,
    take_profit_roe_percent: float,
) -> tuple[float, float]:
    if direction not in {"COMPRA", "VENTA"}:
        raise ValueError("La dirección debe ser COMPRA o VENTA.")
    if not isfinite(entry_price) or entry_price <= 0:
        raise ValueError("El precio de entrada debe ser positivo y finito.")
    if (
        leverage <= 0
        or not isfinite(stop_roe_percent)
        or not isfinite(take_profit_roe_percent)
        or stop_roe_percent <= 0
        or take_profit_roe_percent <= 0
    ):
        raise ValueError("Apalancamiento y porcentajes RoE deben ser positivos.")

    stop_move = stop_roe_percent / (100 * leverage)
    take_profit_move = take_profit_roe_percent / (100 * leverage)
    if direction == "COMPRA":
        return entry_price * (1 - stop_move), entry_price * (1 + take_profit_move)
    return entry_price * (1 + stop_move), entry_price * (1 - take_profit_move)
