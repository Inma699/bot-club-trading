from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from typing import Sequence
from zoneinfo import ZoneInfo


SPAIN_TIMEZONE = ZoneInfo("Europe/Madrid")
BREAKOUT_LEVEL_STEP_USDT = 5_000.0
BREAKOUT_TOUCH_TOLERANCE_PERCENT = 0.0025
BREAKOUT_MIN_4H_TOUCHES = 3
BREAKOUT_MIN_BODY_ATR = 1.5
BTC_STALLED_TRADE_ALERT_AFTER_SECONDS = 4 * 60 * 60
BTC_STALLED_TRADE_ALERT_TARGET_ROE = 30.0
SFP_DIRECTION_MODES = {
    "COMPRA": frozenset({"COMPRA"}),
    "VENTA": frozenset({"VENTA"}),
    "AMBAS": frozenset({"COMPRA", "VENTA"}),
}


def directions_for_mode(mode: str) -> frozenset[str]:
    try:
        return SFP_DIRECTION_MODES[mode]
    except KeyError as error:
        raise ValueError(f"Modo de dirección no válido: {mode}") from error


def is_sfp_trading_window_open(now: datetime | None = None) -> bool:
    now = now or datetime.now(SPAIN_TIMEZONE)
    if now.tzinfo is None:
        raise ValueError("La fecha/hora debe incluir zona horaria.")

    spain_now = now.astimezone(SPAIN_TIMEZONE)
    minutes_since_midnight = spain_now.hour * 60 + spain_now.minute
    return 7 * 60 <= minutes_since_midnight < 22 * 60


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


def calculate_roe_percent(
    direction: str,
    entry_price: float,
    current_price: float,
    leverage: float,
) -> float:
    if direction not in {"COMPRA", "VENTA"}:
        raise ValueError("La dirección debe ser COMPRA o VENTA.")
    if (
        not isfinite(entry_price)
        or not isfinite(current_price)
        or entry_price <= 0
        or current_price <= 0
        or not isfinite(leverage)
        or leverage <= 0
    ):
        raise ValueError("Precio de entrada, precio actual y apalancamiento deben ser positivos.")

    price_change = (current_price - entry_price) / entry_price
    if direction == "VENTA":
        price_change *= -1
    return price_change * leverage * 100


def should_alert_stalled_btc_trade(elapsed_seconds: float, max_roe_percent: float) -> bool:
    return (
        elapsed_seconds >= BTC_STALLED_TRADE_ALERT_AFTER_SECONDS
        and max_roe_percent < BTC_STALLED_TRADE_ALERT_TARGET_ROE
    )


def detect_strong_support_break(
    candles_15m: Sequence[Sequence[float]],
    candles_4h: Sequence[Sequence[float]],
    daily_candles: Sequence[Sequence[float]],
) -> dict[str, float | int] | None:
    closed_15m = candles_15m[:-1]
    if len(closed_15m) < 16:
        return None

    previous_candle = closed_15m[-2]
    breakdown_candle = closed_15m[-1]
    candle_open = float(breakdown_candle[1])
    candle_close = float(breakdown_candle[4])
    previous_close = float(previous_candle[4])
    bearish_body = candle_open - candle_close
    if bearish_body <= 0 or previous_close <= candle_close:
        return None

    atr_candles = closed_15m[-16:-1]
    true_ranges = []
    for index in range(1, len(atr_candles)):
        candle = atr_candles[index]
        previous_atr_close = float(atr_candles[index - 1][4])
        true_ranges.append(
            max(
                float(candle[2]) - float(candle[3]),
                abs(float(candle[2]) - previous_atr_close),
                abs(float(candle[3]) - previous_atr_close),
            )
        )
    if len(true_ranges) != 14:
        return None
    atr_14 = sum(true_ranges) / len(true_ranges)
    if atr_14 <= 0 or bearish_body < atr_14 * BREAKOUT_MIN_BODY_ATR:
        return None

    support_candles_4h = candles_4h[:-1][-90:]
    support_candles_daily = daily_candles[:-1][-30:]
    if len(support_candles_4h) < BREAKOUT_MIN_4H_TOUCHES:
        return None

    first_level = int(candle_close // BREAKOUT_LEVEL_STEP_USDT) + 1
    last_level = int(previous_close // BREAKOUT_LEVEL_STEP_USDT)
    broken_levels = []
    for multiple in range(first_level, last_level + 1):
        level = multiple * BREAKOUT_LEVEL_STEP_USDT
        tolerance = level * BREAKOUT_TOUCH_TOLERANCE_PERCENT
        touches_4h = sum(
            1
            for candle in support_candles_4h
            if float(candle[3]) <= level + tolerance
            and float(candle[2]) >= level - tolerance
        )
        touches_daily = sum(
            1
            for candle in support_candles_daily
            if float(candle[3]) <= level + tolerance
            and float(candle[2]) >= level - tolerance
        )
        if (
            touches_4h >= BREAKOUT_MIN_4H_TOUCHES
            or (touches_daily >= 1 and touches_4h >= 1)
        ):
            broken_levels.append((level, touches_4h, touches_daily))

    if not broken_levels:
        return None

    level, touches_4h, touches_daily = max(broken_levels, key=lambda item: item[0])
    return {
        "level": level,
        "close": candle_close,
        "timestamp": int(breakdown_candle[0]),
        "bearish_body": bearish_body,
        "atr_14": atr_14,
        "strength_atr": bearish_body / atr_14,
        "touches_4h": touches_4h,
        "touches_daily": touches_daily,
    }


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
