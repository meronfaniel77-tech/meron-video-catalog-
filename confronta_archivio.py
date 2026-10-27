
import json
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

# MERON - Confronto intelligente Apple / YouTube

FILE_APPLE = Path("episodi_apple.json")
FILE_YOUTUBE = Path("archivio_youtube.json")
FILE_CATALOGO = Path("videos.json")
FILE_RISULTATI = Path("controllo_video_meron.json")

STOPWORDS = {
    "the", "and", "with", "from", "what", "when",
    "where", "who", "why", "how", "case", "story",
    "true", "crime", "elisa", "part", "episode",
    "this", "that", "into", "after", "before",
    "about", "their", "there", "were", "they",
    "have", "been", "will", "would", "could",
    "some", "more", "very", "also", "only",
    "il", "lo", "la", "gli", "le", "un", "una",
    "uno", "di", "del", "della", "dei", "delle",
    "da", "dal", "dallo", "dalla", "dai",
    "in", "con", "per", "che", "cosa", "caso",
    "storia", "ep", "pt", "parte", "dopo",
    "sono", "era", "alla", "sua", "suo",
    "fatto", "fine", "hanno", "quella", "notte",
    "successo", "verita", "morte", "giorni",
    "nuova", "new", "truth", "questa",
    "questo", "quella", "quello", "dove",
    "come", "quando", "perche", "anche",
    "tutti", "tutte", "essere", "stato",
    "stata", "dentro", "fuori", "ancora",
    "della", "delle", "degli", "nella",
    "nelle", "nello", "negli", "sulla",
    "sulle", "sullo", "agli", "alle",
    "dalla", "dalle", "dello", "delle"
}

# Termini molto comuni nei podcast true crime.
# Non possono essere sufficienti da soli
# per pubblicare automaticamente un video.
GENERICHE = {
    "omicidio", "assassino", "ucciso",
    "morto", "scomparso", "scomparsa",
    "madre", "padre", "figlia", "figlio",
    "famiglia", "marito", "moglie",
    "bambino", "bambini", "scuola",
    "prigione", "agghiacciante",
    "segreto", "lotteria", "matrimonio",
    "anni", "giorni", "storia",
    "delitto", "vittima", "polizia",
    "indagine", "criminale"
}

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
    risultato = set()

    for parola in normalizza(testo).split():
        parola = TRADUZIONI.get(parola, parola)

        if (
            len(parola) >= 4
            and parola not in STOPWORDS
            and not parola.isdigit()
        ):
            risultato.add(parola)

    return risultato


def numero_parte(titolo):
    testo = normalizza(titolo)

    match = re.search(
        r"\b(?:pt|part|parte)\s*([1-9])\b",
        testo
    )

    if match:
        return int(match.group(1))

    return None


def leggi_json(percorso):
    with percorso.open(
        "r", encoding="utf-8"
    ) as file:
        return json.load(file)


def peso_parola(parola, frequenze, totale):
    frequenza = frequenze.get(parola, 0)

    return math.log(
        1 + totale / (1 + frequenza)
    )


def calcola_candidato(
    titolo_apple,
    descrizione_apple,
    titolo_video,
    frequenze,
    totale_video
):
    parole_titolo = parole_importanti(titolo_apple)
    parole_descrizione = parole_importanti(
        descrizione_apple
    )
    parole_video = parole_importanti(titolo_video)

    comuni_titolo = parole_titolo & parole_video

    # La descrizione e' una fonte di supporto,
    # non una prova sufficiente.
    comuni_descrizione = (
        parole_descrizione & parole_video
    ) - comuni_titolo

    specifiche_titolo = (
        comuni_titolo - GENERICHE
    )

    specifiche_descrizione = (
        comuni_descrizione - GENERICHE
    )

    punteggio_titolo = sum(
        peso_parola(p, frequenze, totale_video)
        for p in comuni_titolo
    )

    punteggio_descrizione = sum(
        peso_parola(p, frequenze, totale_video)
        for p in specifiche_descrizione
    )

    # Il titolo pesa piu' della descrizione.
    punteggio = (
        punteggio_titolo
        + punteggio_descrizione * 0.45
    )

    # Bonus se coincidono almeno due parole
    # specifiche del titolo.
    if len(specifiche_titolo) >= 2:
        punteggio += 2

    # Bonus limitato per le descrizioni.
    if len(specifiche_descrizione) >= 2:
        punteggio += 0.8

    # Evita che descrizioni lunghe dominino.
    punteggio = round(punteggio, 3)

    comuni = sorted(
        comuni_titolo | comuni_descrizione
    )

    return {
        "score": punteggio,
        "common": comuni,
        "title_matches": len(specifiche_titolo),
        "description_matches": len(
            specifiche_descrizione
        )
    }


def controlla():
    dati_apple = leggi_json(FILE_APPLE)
    dati_youtube = leggi_json(FILE_YOUTUBE)
    dati_catalogo = leggi_json(FILE_CATALOGO)

    episodi = dati_apple.get("episodes", [])
    video = dati_youtube.get("videos", [])
    catalogo = dati_catalogo.get("videos", {})

    if not isinstance(episodi, list):
        raise ValueError("Archivio Apple non valido")

    if not isinstance(video, list):
        raise ValueError("Archivio YouTube non valido")

    if not isinstance(catalogo, dict):
        raise ValueError("Catalogo MerON non valido")

    frequenze = Counter()

    for elemento in video:
        frequenze.update(
            parole_importanti(elemento.get("title", ""))
        )

    risultati = []

    for episodio in episodi:
        episodio_id = str(episodio.get("id", ""))
        titolo = episodio.get("titolo", "")
        descrizione = episodio.get(
            "descrizione", ""
        )

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

            # Evita parti esplicitamente diverse.
            parte_apple = numero_parte(titolo)
            parte_video = numero_parte(
                titolo_video
            )

            if parte_apple != parte_video:
                continue

            analisi = calcola_candidato(
                titolo,
                descrizione,
                titolo_video,
                frequenze,
                len(video)
            )

            if not analisi["common"]:
                continue

            candidati.append({
                "title": titolo_video,
                "url": url,
                **analisi
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

            # Le descrizioni aiutano a trovare
            # candidati, ma per la pubblicazione
            # servono almeno due parole specifiche
            # nel titolo Apple.
            if (
                primo["title_matches"] >= 2
                and primo["score"] >= 5.0
                and (
                    secondo == 0
                    or primo["score"] > secondo * 1.5
                )
            ):
                stato = "CANDIDATO_FORTE"

        risultati.append({
            "trackId": episodio.get("id"),
            "episode": titolo,
            "status": stato,
            "candidates": migliori
        })

    # Controllo duplicati tra candidati forti.
    utilizzi = defaultdict(list)

    for risultato in risultati:
        if (
            risultato["status"] == "CANDIDATO_FORTE"
            and risultato["candidates"]
        ):
            url = risultato["candidates"][0]["url"]
            utilizzi[url].append(risultato)

    for url, associati in utilizzi.items():
        if len(associati) > 1:
            for risultato in associati:
                risultato["status"] = "DA_VERIFICARE"

    forti = sum(
        1 for risultato in risultati
        if risultato["status"] == "CANDIDATO_FORTE"
    )

    gia_collegati = sum(
        1 for risultato in risultati
        if str(risultato["trackId"]) in catalogo
    )

    print("MERON - CONTROLLO CON DESCRIZIONI")
    print("Episodi Apple:", len(episodi))
    print("Video YouTube:", len(video))
    print("Candidati forti:", forti)
    print(
        "Da verificare:",
        len(risultati) - forti
    )
    print(
        "Episodi gia' nel catalogo:",
        gia_collegati
    )

    with FILE_RISULTATI.open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            {"results": risultati},
            file,
            ensure_ascii=False,
            indent=2
        )
        file.write("\n")

    print(
        "Creato controllo_video_meron.json"
    )


if __name__ == "__main__":
    controlla()
