
import json
import re
import unicodedata
import urllib.request

APPLE_PODCAST_ID = "1628126740"
ARCHIVIO_FILE = "archivio_youtube.json"

PAROLE_DA_IGNORARE = {
    "the", "and", "with", "from", "what", "when",
    "where", "who", "why", "how", "case", "story",
    "true", "crime", "elisa", "part", "episode",
    "il", "lo", "la", "i", "gli", "le", "un", "una",
    "di", "del", "della", "dei", "delle", "da",
    "in", "con", "per", "che", "cosa", "caso",
    "storia", "ep", "pt", "parte", "dopo",
    "sono", "era", "alla", "sua", "suo"
}


def normalizza(testo):
    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(
        carattere for carattere in testo
        if not unicodedata.combining(carattere)
    )
    testo = testo.lower()
    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def parole_importanti(testo):
    parole = normalizza(testo).split()

    return {
        parola for parola in parole
        if len(parola) >= 4
        and parola not in PAROLE_DA_IGNORARE
        and not parola.isdigit()
    }


def recupera_episodi():
    url = (
        "https://itunes.apple.com/lookup"
        f"?id={APPLE_PODCAST_ID}"
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

    return [
        episodio
        for episodio in dati.get("results", [])
        if episodio.get("wrapperType") == "podcastEpisode"
    ]


def confronta():
    with open(
        ARCHIVIO_FILE, "r", encoding="utf-8"
    ) as file:
        archivio = json.load(file)

    videos = archivio.get("videos", [])
    episodi = recupera_episodi()

    print("MERON - CONFRONTO ARCHIVIO STORICO")
    print(f"Episodi Apple: {len(episodi)}")
    print(f"Video YouTube: {len(videos)}")
    print()

    risultati = []

    for episodio in episodi:
        titolo_episodio = episodio.get("trackName", "")
        parole_episodio = parole_importanti(titolo_episodio)

        if not parole_episodio:
            continue

        candidati = []

        for video in videos:
            titolo_video = video.get("title", "")
            parole_video = parole_importanti(titolo_video)

            comuni = parole_episodio & parole_video

            if not comuni:
                continue

            punteggio = len(comuni) / min(
                len(parole_episodio),
                len(parole_video)
            )

            if len(comuni) >= 2 and punteggio >= 0.5:
                candidati.append({
                    "title": titolo_video,
                    "url": video.get("url", ""),
                    "score": round(punteggio, 2),
                    "common": sorted(comuni)
                })

        candidati.sort(
            key=lambda elemento: elemento["score"],
            reverse=True
        )

        if candidati:
            risultati.append({
                "trackId": episodio.get("trackId"),
                "episode": titolo_episodio,
                "candidates": candidati[:3]
            })

    with open(
        "corrispondenze_da_verificare.json",
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            {"matches": risultati},
            file,
            ensure_ascii=False,
            indent=2
        )

    print(
        "Episodi con possibili corrispondenze:",
        len(risultati)
    )

    for risultato in risultati[:15]:
        print()
        print("APPLE:", risultato["episode"])

        for candidato in risultato["candidates"]:
            print("YOUTUBE:", candidato["title"])
            print("URL:", candidato["url"])
            print("Parole comuni:", candidato["common"])
            print("Punteggio:", candidato["score"])

    print()
    print(
        "Risultati salvati in "
        "corrispondenze_da_verificare.json"
    )


if __name__ == "__main__":
    confronta()
