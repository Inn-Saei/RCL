"""
Script : génère un fichier .ics (calendrier) des matchs du RC Lens
en scrapant le calendrier officiel du club.

Installation :
    pip install requests beautifulsoup4 icalendar

Usage :
    python rclens_calendrier.py
"""

import re
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from icalendar import Calendar, Event

URL = "https://www.rclens.fr/fr/equipe-premiere/calendrier"

MOIS = {
    "janvier": 1, "février": 2, "fevrier": 2, "mars": 3, "avril": 4,
    "mai": 5, "juin": 6, "juillet": 7, "août": 8, "aout": 8,
    "septembre": 9, "octobre": 10, "novembre": 11,
    "décembre": 12, "decembre": 12,
}

DATE_RE = re.compile(r"(\d{1,2})\s+(\w+)\s+(\d{4})", re.IGNORECASE)
TIME_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")


def fetch_html(url: str = URL) -> str:
    """Récupère le HTML de la page calendrier."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0 Safari/537.36"
        )
    }
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    return resp.text


def parse_matches(html: str) -> list[dict]:
    """
    Parcourt les blocs répétés de la page (typiquement des <li>) et en
    extrait date, heure, équipes, compétition et stade via des regex sur
    le texte. Cette approche évite de dépendre de noms de classes CSS
    précis, qu'il n'a pas été possible de vérifier depuis cet environnement.
    """
    soup = BeautifulSoup(html, "html.parser")
    matches = []

    candidates = soup.select("li")

    for li in candidates:
        text = li.get_text(" ", strip=True)

        date_m = DATE_RE.search(text)
        time_m = TIME_RE.search(text)
        if not date_m or not time_m:
            continue

        day, month_name, year = date_m.groups()
        month = MOIS.get(month_name.lower())
        if not month:
            continue

        hour, minute = map(int, time_m.groups())

        # Équipes : on essaie d'abord via les attributs alt des logos <img>
        imgs = li.find_all("img")
        teams = [
            img.get("alt", "").strip()
            for img in imgs
            if img.get("alt") and "logo" not in img.get("alt", "").lower()
        ]

        # Fallback : extraction depuis le texte brut si pas assez de logos
        if len(teams) < 2:
            after_time = text.split(time_m.group(0), 1)[-1]
            parts = re.split(r"\s+(?:vs\.?|-|–|\.\.\.)\s+", after_time)
            parts = [p.strip() for p in parts if p.strip()]
            teams = parts[:2]

        if len(teams) < 2:
            continue

        home, away = teams[0], teams[1]

        # Compétition (ex: "Ligue 1 McDonald's - Journée 3")
        competition = ""
        comp_tag = li.find(class_=re.compile("compet", re.I))
        if comp_tag:
            competition = comp_tag.get_text(strip=True)

        # Stade
        venue = ""
        venue_tag = li.find(class_=re.compile("stade|venue|lieu", re.I))
        if venue_tag:
            venue = venue_tag.get_text(strip=True)

        try:
            start = datetime(
                year=int(year), month=month, day=int(day),
                hour=hour, minute=minute,
            )
        except ValueError:
            continue

        matches.append({
            "date": start,
            "home": home,
            "away": away,
            "competition": competition,
            "venue": venue,
        })

    # Dédoublonnage (une même rencontre peut apparaître dans plusieurs <li>
    # imbriqués)
    seen = set()
    uniques = []
    for m in matches:
        key = (m["date"], m["home"], m["away"])
        if key not in seen:
            seen.add(key)
            uniques.append(m)

    return uniques


def build_calendar(matches: list[dict], duration_hours: int = 2) -> Calendar:
    """Construit l'objet Calendar à partir de la liste de matchs."""
    cal = Calendar()
    cal.add("prodid", "-//Calendrier RC Lens//scraper//FR")
    cal.add("version", "2.0")

    for m in matches:
        event = Event()
        event.add("summary", f"{m['home']} - {m['away']}")
        event.add("dtstart", m["date"])
        event.add("dtend", m["date"] + timedelta(hours=duration_hours))
        if m["venue"]:
            event.add("location", m["venue"])
        if m["competition"]:
            event.add("description", m["competition"])
        cal.add_component(event)

    return cal


def main():
    print("Récupération de la page...")
    html = fetch_html()

    print("Extraction des matchs...")
    matches = parse_matches(html)
    print(f"{len(matches)} match(s) trouvé(s).")

    if not matches:
        print(
            "Aucun match trouvé. La page charge peut-être son contenu "
            "en JavaScript (voir la remarque en bas du script)."
        )
        return

    cal = build_calendar(matches)
    filename = "calendrier_rclens.ics"
    with open(filename, "wb") as f:
        f.write(cal.to_ical())

    print(f"Fichier {filename} généré avec succès.")


if __name__ == "__main__":
    main()

# ---------------------------------------------------------------------------
# REMARQUE IMPORTANTE
# ---------------------------------------------------------------------------
# Cette page affiche un compte à rebours dynamique ("02 J 21 H 13 Min") sur
# le prochain match, ce qui suggère qu'une partie du contenu pourrait être
# injectée en JavaScript. Si `parse_matches` renvoie 0 résultat malgré une
# requête HTTP réussie (code 200), c'est probablement le cas : `requests`
# récupère alors une coquille HTML vide de données.
#
# Solution dans ce cas : remplacer `fetch_html()` par une récupération via
# un navigateur headless (Playwright), qui exécute le JavaScript avant de
# renvoyer le HTML complet :
#
#     pip install playwright
#     playwright install chromium
#
#     from playwright.sync_api import sync_playwright
#
#     def fetch_html(url=URL):
#         with sync_playwright() as p:
#             browser = p.chromium.launch()
#             page = browser.new_page()
#             page.goto(url, wait_until="networkidle")
#             html = page.content()
#             browser.close()
#         return html
#
# Il faudra alors réinjecter cette fonction à la place de la version
# `requests` ci-dessus. Le reste du script (parse_matches, build_calendar)
# reste inchangé.
# ---------------------------------------------------------------------------
