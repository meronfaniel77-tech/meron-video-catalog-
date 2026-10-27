
import json
import re
import unicodedata
import urllib.request
from collections import Counter

APPLE_PODCAST_ID = "1628126740"

STOPWORDS = {
    "the", "and", "with", "from", "what", "when",
    "where", "who", "why", "how", "case", "story",
    "true", "crime", "elisa", "part", "episode",
    "il", "lo", "la", "gli", "le", "un", "una",
    "di", "del", "della", "dei", "delle", "da",
    "in", "con", "per", "che", "cosa", "caso",
    "storia", "ep", "pt", "parte", "dopo",
    "sono", "era", "alla", "sua", "suo",
    "fatto", "fine", "hanno", "quella", "notte",
    "successo", "verita", "morte", "giorni",
    "dalla", "nuova", "new", "truth"
}


def normalizza(testo):
    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(
        c for c in testo
        if not unicodedata.combining(c)
    )
    testo = testo.lower()
    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def parole_importanti(testo):
    return {
        parola
        for parola in normalizza(testo).split()
        if len(parola) >= 4
        and parola not in STOPWORDS
        and not parola.isdigit()
    }


def numero_parte(titolo):
    testo = normalizza(titolo)

    match = re.search(
        r"\b(?:pt|part|parte)\s*([12])\b",
        testo
    )

    if match:
        return int(match.group(1))

    return None


def scarica_episodi():
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
        elemento
        for elemento in dati.get("results", [])
        if elemento.get("wrapperType") == "podcastEpisode"
    ]


def controlla():
    with open(
        "archivio_youtube.json",
        encoding="utf-8"
    ) as file:
        video = json.load(file).get("videos", [])

    episodi = scarica_episodi()

    # Conta le parole presenti nei diversi titoli.
    frequenze = Counter()

    for elemento in video:
        frequenze.update(
            parole_importanti(elemento.get("title", ""))
        )

    risultati = []

    for episodio in episodi:
        titolo = episodio.get("trackName", "")
        parole = parole_importanti(titolo)

        candidati = []

        for elemento in video:
            titolo_video = elemento.get("title", "")
            parole_video = parole_importanti(titolo_video)
            comuni = parole & parole_video

            if not comuni:
                continue

            # Le parole rare pesano di piu'.
            punteggio = sum(
                1 / max(1, frequenze[parola])
                for parola in comuni
            )

            candidati.append({
                "title": titolo_video,
                "url": elemento.get("url", ""),
                "score": round(punteggio, 3),
                "common": sorted(comuni)
            })

        candidati.sort(
            key=lambda x: x["score"],
            reverse=True
        )

        migliori = candidati[:3]

        stato = "DA_VERIFICARE"

        if migliori:
            primo = migliori[0]
            secondo = (
                migliori[1]["score"]
                if len(migliori) > 1
                else 0
            )

            parte_apple = numero_parte(titolo)
            parte_youtube = numero_parte(
                primo["title"]
            )

            parti_compatibili = (
                parte_apple == parte_youtube
                if parte_apple is not None
                else parte_youtube is None
            )

            parole_comuni = len(primo["common"])

            if (
                parole_comuni >= 2
                and primo["score"] >= 1.5
                and primo["score"] > secondo * 1.5
                and parti_compatibili
            ):
                stato = "CANDIDATO_FORTE"

        risultati.append({
            "trackId": episodio.get("trackId"),
            "episode": titolo,
            "status": stato,
            "candidates": migliori
        })

    forti = sum(
        1 for r in risultati
        if r["status"] == "CANDIDATO_FORTE"
    )

    print("MERON - CONTROLLO DI SICUREZZA")
    print("Episodi Apple:", len(episodi))
    print("Video YouTube:", len(video))
    print("Candidati forti:", forti)
    print(
        "Da verificare:",
        len(risultati) - forti
    )

    with open(
        "controllo_video_meron.json",
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            {"results": risultati},
            file,
            ensure_ascii=False,
            indent=2
        )

    print("Creato controllo_video_meron.json")
    print("Nessun video pubblicato automaticamente.")


if __name__ == "__main__":
    controlla()
