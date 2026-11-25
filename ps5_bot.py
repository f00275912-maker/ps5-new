#!/usr/bin/env python3
"""
Marktplaats PS5 deal-bot
Mailt je zodra er een PlayStation 5 console onder de maximumprijs wordt geplaatst.

Gebruik:
    pip install requests
    export GMAIL_ADRES="jouwadres@gmail.com"
    export GMAIL_APP_WACHTWOORD="xxxx xxxx xxxx xxxx"
    python ps5_bot.py            # blijft draaien, controleert elke 10 min
    python ps5_bot.py --once     # één keer controleren (voor cron / GitHub Actions)
    python ps5_bot.py --test     # stuurt een testmail
"""

import json
import os
import re
import smtplib
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path

import requests

# ----------------------- INSTELLINGEN -----------------------
MAX_PRIJS = 550          # euro
MIN_PRIJS = 200          # alles daaronder is meestal een accessoire, nepadvertentie of oplichting
ZOEKTERMEN = ["playstation 5", "ps5 console", "ps5 digital", "playstation 5 disc"]
CONTROLEER_ELKE_SECONDEN = 600   # 10 minuten, niet te laag zetten
ONTVANGER = os.environ.get("GMAIL_ADRES", "")  # mail naar jezelf

# Titel moet een van deze bevatten
MOET_BEVATTEN = ["ps5", "playstation 5", "playstation5", "ps 5"]

# Titel mag geen van deze bevatten (accessoires, defecte of gezochte consoles, enz.)
UITSLUITEN = [
    "gezocht", "gevraagd", "defect", "kapot", "voor onderdelen", "onderdelen",
    "hoesje", "standaard", "stand ", "dock", "oplader",
    "headset", "pulse", "camera", "afstandsbediening", "remote", "skin", "sticker",
    "ssd", "koeling", "case", "tas ",
    "ruil", "ruilen", "ps4", "ps3", "playstation 4", "playstation 3",
    "vr", "portal", "disc drive", "diskdrive", "los ", "kabel", "pro ",
    "bieden vanaf", "reserveren",
]
# ------------------------------------------------------------

API_URL = "https://www.marktplaats.nl/lrp/api/search"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "nl-NL,nl;q=0.9",
}
SEEN_FILE = Path(__file__).with_name("gezien.json")


def laad_gezien():
    if SEEN_FILE.exists():
        try:
            return set(json.loads(SEEN_FILE.read_text()))
        except Exception:
            pass
    return set()


def bewaar_gezien(gezien):
    # houd het bestand klein
    SEEN_FILE.write_text(json.dumps(sorted(gezien)[-5000:]))


def zoek(term):
    params = {
        "query": term,
        "limit": 50,
        "offset": 0,
        "sortBy": "SORT_INDEX",
        "sortOrder": "DECREASING",   # nieuwste eerst
        "searchInTitleAndDescription": "true",
        "viewOptions": "list-view",
    }
    r = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return r.json().get("listings", [])


def prijs_in_euro(listing):
    info = listing.get("priceInfo") or {}
    cents = info.get("priceCents")
    if cents is None:
        return None
    return cents / 100


def is_goede_deal(listing):
    titel = (listing.get("title") or "").lower()
    prijs = prijs_in_euro(listing)
    if prijs is None or not (MIN_PRIJS <= prijs <= MAX_PRIJS):
        return False
    if not any(w in titel for w in MOET_BEVATTEN):
        return False
    if any(w in titel + " " for w in UITSLUITEN):
        return False
    return True


def advertentie_url(listing):
    url = listing.get("vipUrl") or ""
    if url.startswith("/"):
        url = "https://www.marktplaats.nl" + url
    return url


def stuur_mail(deals):
    adres = os.environ.get("GMAIL_ADRES")
    wachtwoord = os.environ.get("GMAIL_APP_WACHTWOORD")
    if not adres or not wachtwoord:
        print("!! GMAIL_ADRES / GMAIL_APP_WACHTWOORD niet ingesteld, mail niet verstuurd")
        return False

    regels = []
    for d in deals:
        loc = (d.get("location") or {}).get("cityName", "")
        regels.append(
            f"{d.get('title')}\n"
            f"Prijs: €{prijs_in_euro(d):.2f}   Plaats: {loc}\n"
            f"{advertentie_url(d)}\n"
        )
    onderwerp = f"PS5 deal: {len(deals)} nieuwe advertentie(s) onder €{MAX_PRIJS}"
    bericht = MIMEText("\n".join(regels), "plain", "utf-8")
    bericht["Subject"] = onderwerp
    bericht["From"] = adres
    bericht["To"] = ONTVANGER or adres

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(adres, re.sub(r"\s", "", wachtwoord))
        s.send_message(bericht)
    return True


def controleer(gezien, eerste_keer):
    nieuwe_deals = []
    for term in ZOEKTERMEN:
        try:
            listings = zoek(term)
        except Exception as e:
            print(f"Zoeken naar '{term}' mislukt: {e}")
            continue
        for l in listings:
            item_id = str(l.get("itemId"))
            if item_id in gezien:
                continue
            gezien.add(item_id)
            if not eerste_keer and is_goede_deal(l):
                nieuwe_deals.append(l)
        time.sleep(2)  # rustig aan met de verzoeken

    if nieuwe_deals:
        print(f"{len(nieuwe_deals)} nieuwe deal(s) gevonden")
        stuur_mail(nieuwe_deals)
    else:
        print(time.strftime("%H:%M"), "- geen nieuwe deals")
    bewaar_gezien(gezien)


def main():
    if "--test" in sys.argv:
        test = {
            "title": "TEST - PlayStation 5 console",
            "priceInfo": {"priceCents": 49900},
            "vipUrl": "https://www.marktplaats.nl",
            "location": {"cityName": "Leeuwarden"},
        }
        print("Testmail verstuurd" if stuur_mail([test]) else "Testmail mislukt")
        return

    eerste_keer = not SEEN_FILE.exists()
    gezien = laad_gezien()
    if eerste_keer:
        print("Eerste run: bestaande advertenties worden genegeerd, alleen nieuwe worden gemeld.")

    controleer(gezien, eerste_keer)
    if "--once" in sys.argv:
        return
    while True:
        time.sleep(CONTROLEER_ELKE_SECONDEN)
        controleer(gezien, False)


if __name__ == "__main__":
    main()
