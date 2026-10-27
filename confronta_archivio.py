
import json
import math
import re
import unicodedata
import urllib.request
from collections import Counter, defaultdict

APPLE_PODCAST_ID = "1628126740"

STOPWORDS = {
    "the", "and", "with", "from", "what", "when",
    "where", "who", "why", "how", "case", "story",
    "true", "crime", "elisa", "part", "episode",
    "this", "that", "into", "after", "before",
    "about", "their", "there", "were", "they",
    "il", "lo", "la", "gli", "le", "un", "una",
    "di", "del", "della", "dei", "delle", "da",
    "in", "con", "per", "che", "cosa", "caso",
    "storia", "ep", "pt", "parte", "dopo",
    "sono", "era", "alla", "sua", "suo",
    "fatto", "fine", "hanno", "quella", "notte",
    "successo", "verita", "morte", "giorni",
    "dalla", "nuova", "new", "truth"
}

# Piccolo dizionario bilingue.
# Le parole generiche non bastano da sole
# per dichiarare un collegamento forte.
TRADUZIONI = {
    "murder": "omicidio",
    "murdered": "omicidio",
    "killer": "assassino",
    "killed": "ucciso",
    "death": "morte",
    "dead": "morto",
    "missing": "scomparso",
    "disappeared": "scomparso",
    "disappearance": "scomparsa",
    "daughter": "figlia",
    "son": "figlio",
    "mother": "madre",
    "father": "padre",
    "husband": "marito",
    "wife": "moglie",
    "family": "famiglia",
    "marriage": "matrimonio",
    "wedding": "matrimonio",
    "days": "giorni",
    "years": "anni",
    "truth": "verita",
    "secret": "segreto",
    "secrets": "segreto",
    "chilling": "agghiacciante",
    "horrifying": "agghiacciante",
    "hide": "nascondino",
    "seek": "nascondino",
    "lottery": "lotteria",
    "shark": "squalo",
    "sharks": "squalo",
    "school": "scuola",
    "prison": "prigione",
    "baby": "bambino",
    "child": "bambino",
    "children": "bambini"
}


def normalizza(testo):
    testo = unicodedata.normalize(
        "NFKD", str(testo or "")
    )
    testo = "".join(
        c for c in testo
        if not unicodedata.combining(c)
    )
    testo = testo.lower()
    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()


def parole_importanti(testo):
    parole = set()

    for parola in normalizza(testo).split():
        parola = TRADUZIONI.get(parola, parola)

        if (
            len(parola) >= 4
            and parola not in STOPWORDS
            and not parola.isdigit()
        ):
            parole.add(parola)

    return parole


def numero_parte(titolo):
    testo = normalizza(titolo)

    match = re.search(
        r"\b(?:pt|part|parte)\s*([1-9])\b",
        testo
    )

    if match:
        return int(match.group(1))

    return None


def parti_compatibili(titolo_apple, titolo_video):
    parte_apple = numero_parte(titolo_apple)
    parte_video = numero_parte(titolo_video)

    return parte_apple == parte_video


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


def punteggio_corrispondenza(
    parole_apple,
    parole_video,
    frequenze,
    totale_video
):
    comuni = parole_apple & parole_video

    if not comuni:
        return 0, []

    punteggio = 0

    for parola in comuni:
        frequenza = frequenze.get(parola, 0)

        # Le parole rare hanno maggiore peso.
        peso = math.log(
            1 + totale_video / (1 + frequenza)
        )

        punteggio += peso

    # Premia i titoli che condividono
    # una percentuale elevata di parole.
    unione = parole_apple | parole_video

    copertura = (
        len(comuni) / len(unione)
        if unione else 0
    )

    punteggio += copertura * 2

    return round(punteggio, 3), sorted(comuni)


def controlla():
    with open(
        "archivio_youtube.json",
        encoding="utf-8"
    ) as file:
        video = json.load(file).get("videos", [])

    episodi = scarica_episodi()

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
            url = elemento.get("url", "")

            if not isinstance(url, str):
                continue

            if not url.startswith(
                "https://www.youtube.com/watch?v="
            ):
                continue

            if not parti_compatibili(
                titolo, titolo_video
            ):
                continue

            parole_video = parole_importanti(
                titolo_video
            )

            score, comuni = punteggio_corrispondenza(
                parole,
                parole_video,
                frequenze,
                len(video)
            )

            if not comuni:
                continue

            candidati.append({
                "title": titolo_video,
                "url": url,
                "score": score,
                "common": comuni
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

            parole_comuni = len(primo["common"])

            # Regole prudenti per l'abbinamento.
            if (
                parole_comuni >= 2
                and primo["score"] >= 4.5
                and (
                    secondo == 0
                    or primo["score"] > secondo * 1.5
                )
            ):
                stato = "CANDIDATO_FORTE"

        risultati.append({
            "trackId": episodio.get("trackId"),
            "episode": titolo,
            "status": stato,
            "candidates": migliori
        })

    # Evita di proporre lo stesso video come
    # collegamento forte per episodi diversi.
    utilizzi = defaultdict(list)

    for risultato in risultati:
        if (
            risultato["status"] == "CANDIDATO_FORTE"
            and risultato["candidates"]
        ):
            url = risultato["candidates"][0]["url"]
            utilizzi[url].append(risultato)

    duplicati = 0

    for url, associati in utilizzi.items():
        if len(associati) > 1:
            duplicati += len(associati)

            for risultato in associati:
                risultato["status"] = "DA_VERIFICARE"

    forti = sum(
        1 for risultato in risultati
        if risultato["status"] == "CANDIDATO_FORTE"
    )

    print("MERON - CONTROLLO MIGLIORATO")
    print("Episodi Apple:", len(episodi))
    print("Video YouTube:", len(video))
    print("Candidati forti:", forti)
    print("Da verificare:", len(risultati) - forti)
    print("Esclusi per duplicati:", duplicati)

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
    print("Nessun video pubblicato direttamente.")


if __name__ == "__main__":
    controlla()
