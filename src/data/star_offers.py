# src/data/star_offers.py

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class StarOffer:
    """
    Оффер пополнения через Telegram Stars.

    code            — внутренний код оффера (для callback_data и БД)
    title           — название для пользователя
    description     — описание в инвойсе
    amount_stars    — сколько звёзд списывается
    credits         — сколько фотосессий даём за покупку
    """
    code: str
    title: str
    description: str
    amount_stars: int
    credits: int


STAR_OFFERS: List[StarOffer] = [
    StarOffer(
        code="photoshoot_1",
        title="1 фотосессия",
        description="Одна фотосессия в любом стиле в 4K-качестве.",
        amount_stars=100,
        credits=1,
    ),
    StarOffer(
        code="photoshoot_5",
        title="5 фотосессий",
        description="Пакет из пяти фотосессий по выгодной цене.",
        amount_stars=450,
        credits=5,
    ),
    StarOffer(
        code="photoshoot_10",
        title="10 фотосессий",
        description="Максимальная выгода — 10 стильных фотосессий.",
        amount_stars=800,
        credits=10,
    ),
]


def get_offer_by_code(code: str) -> Optional[StarOffer]:
    for offer in STAR_OFFERS:
        if offer.code == code:
            return offer
    return None
