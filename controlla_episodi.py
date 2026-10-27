
import json
import re
import unicodedata
import urllib.request
from difflib import SequenceMatcher

# MERON - Recupera gli episodi da Apple Podcasts
PODCAST_ID = "1628126740"


# MERON - Normalizza i titoli per confrontarli
def normalizza_titolo(titolo):
    titolo = unicodedata.normalize("NFKD", titolo)

    titolo = "".join(
        carattere
        for carattere in titolo
        if not unicodedata.combining(carattere)
    )

    titolo = titolo.lower()

    # Elimina la numerazione iniziale degli episodi
    titolo = re.sub(
        r"^\s*ep\.?\s*\d+\s*[:.\-]?\s*",
        "",
        titolo
    )

    # Elimina punteggiatura e spazi ripetuti
    titolo = re.sub(r"[^a-z0-9\s]", " ", titolo)
    titolo = re.sub(r"\s+", " ", titolo).strip()

    return titolo


# MERON - Calcola la somiglianza tra due titoli
def somiglianza_titoli(titolo1, titolo2):
    pulito1 = normalizza_titolo(titolo1)
    pulito2 = normalizza_titolo(titolo2)

    if not pulito1 or not pulito2:
        return 0.0

    return SequenceMatcher(
        None,
        pulito1,
        pulito2
    ).ratio()


# MERON - Recupera gli episodi e confronta i video YouTube
def recupera_episodi():
    url = (
        "https://itunes.apple.com/lookup"
        f"?id={PODCAST_ID}&entity=podcastEpisode&limit=200"
    )

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "MerON/1.0"}
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)

    episodi = []

    for item in data.get("results", []):
        if item.get("kind") != "podcast-episode":
            continue

        episodi.append({
            "id": item.get("trackId"),
            "titolo": item.get("trackName", ""),
            "data": item.get("releaseDate", "")
        })

    print(f"Episodi Apple Podcasts trovati: {len(episodi)}")

    # MERON - Legge i video YouTube recenti
    try:
        with open("video_recenti.json", "r", encoding="utf-8") as file:
            dati_video = json.load(file)

        video_youtube = dati_video.get("videos", [])

    except FileNotFoundError:
        print("MERON - File video_recenti.json non trovato")
        video_youtube = []

    print(f"\nMERON - Video da confrontare: {len(video_youtube)}")

    # MERON - Cerca possibili corrispondenze
    corrispondenze = 0

    for episodio in episodi:
        for video in video_youtube:
            punteggio = somiglianza_titoli(
                episodio["titolo"],
                video["title"]
            )

            if punteggio >= 0.75:
                corrispondenze += 1

                print("\nPOSSIBILE CORRISPONDENZA:")
                print(f"Episodio: {episodio['titolo']}")
                print(f"ID Apple: {episodio['id']}")
                print(f"Video: {video['title']}")
                print(f"YouTube: {video['url']}")
                print(f"Somiglianza: {punteggio:.0%}")

    print("\nMERON - RISULTATO DEL CONFRONTO")
    print(f"Episodi analizzati: {len(episodi)}")
    print(f"Video analizzati: {len(video_youtube)}")
    print(f"Possibili corrispondenze: {corrispondenze}")

    # MERON - Mostra i primi 10 titoli normalizzati
    print("\nMERON - TEST CONFRONTO TITOLI")

    for episodio in episodi[:10]:
        titolo_originale = episodio["titolo"]
        titolo_pulito = normalizza_titolo(titolo_originale)

        print(f"ORIGINALE: {titolo_originale}")
        print(f"PULITO:    {titolo_pulito}")
        print("---")

    # MERON - Mostra gli ID dei primi 10 episodi
    for episodio in episodi[:10]:
        print(
            f"{episodio['id']} - {episodio['titolo']}"
        )


if __name__ == "__main__":
    recupera_episodi()
