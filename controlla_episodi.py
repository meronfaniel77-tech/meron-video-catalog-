
import json
import re
import unicodedata
import urllib.request
from difflib import SequenceMatcher

# MERON - Recupera episodi e descrizioni Apple Podcasts
PODCAST_ID = "1628126740"
OUTPUT_FILE = "episodi_apple.json"


def normalizza_titolo(titolo):
    titolo = unicodedata.normalize(
        "NFKD", str(titolo or "")
    )

    titolo = "".join(
        carattere
        for carattere in titolo
        if not unicodedata.combining(carattere)
    )

    titolo = titolo.lower()

    titolo = re.sub(
        r"^\s*ep\.?\s*\d+\s*[:.\-]?\s*",
        "",
        titolo
    )

    titolo = re.sub(r"[^a-z0-9\s]", " ", titolo)
    titolo = re.sub(r"\s+", " ", titolo).strip()

    return titolo


def somiglianza_titoli(titolo1, titolo2):
    pulito1 = normalizza_titolo(titolo1)
    pulito2 = normalizza_titolo(titolo2)

    if not pulito1 or not pulito2:
        return 0.0

    return SequenceMatcher(
        None, pulito1, pulito2
    ).ratio()


def recupera_episodi():
    url = (
        "https://itunes.apple.com/lookup"
        f"?id={PODCAST_ID}"
        "&entity=podcastEpisode&limit=200"
    )

    richiesta = urllib.request.Request(
        url,
        headers={"User-Agent": "MerON/1.0"}
    )

    with urllib.request.urlopen(
        richiesta, timeout=30
    ) as risposta:
        dati = json.load(risposta)

    episodi = []
    descrizioni_trovate = 0

    for item in dati.get("results", []):
        if item.get("kind") != "podcast-episode":
            continue

        descrizione = item.get("description") or ""

        if not isinstance(descrizione, str):
            descrizione = ""

        if descrizione.strip():
            descrizioni_trovate += 1

        episodi.append({
            "id": item.get("trackId"),
            "titolo": item.get("trackName", ""),
            "data": item.get("releaseDate", ""),
            "descrizione": descrizione
        })

    if not episodi:
        raise RuntimeError(
            "Nessun episodio recuperato da Apple Podcasts"
        )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            {"episodes": episodi},
            file,
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")

    print("MERON - ARCHIVIO APPLE PODCASTS")
    print("Episodi recuperati:", len(episodi))
    print(
        "Descrizioni disponibili:",
        descrizioni_trovate
    )
    print("Archivio salvato:", OUTPUT_FILE)

    # Mostra solo un breve esempio,
    # senza stampare tutte le descrizioni.
    for episodio in episodi[:3]:
        print("---")
        print("Episodio:", episodio["titolo"])
        print(
            "Lunghezza descrizione:",
            len(episodio["descrizione"])
        )


if __name__ == "__main__":
    recupera_episodi()
