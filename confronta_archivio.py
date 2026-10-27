
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
    "just", "than", "then", "them", "over",
    "under", "through", "behind", "inside",
    "il", "lo", "la", "gli", "le", "un", "una",
    "uno", "di", "del", "della", "dei", "delle",
    "da", "dal", "dallo", "dalla", "dai",
    "in", "con", "per", "che", "cosa", "caso",
    "storia", "ep", "pt", "parte", "dopo",
    "sono", "era", "alla", "sua", "suo",
    "fatto", "fine", "hanno", "quella", "notte",
    "successo", "verita", "morte", "giorni",
    "nuova", "new", "truth", "questa",
    "questo", "quello", "dove", "come",
    "quando", "perche", "anche", "tutti",
    "tutte", "essere", "stato", "stata",
    "dentro", "fuori", "ancora", "degli",
    "nella", "nelle", "nello", "negli",
    "sulla", "sulle", "sullo", "agli",
    "alle", "dalle", "dello", "dell",
    "dall", "loro", "suoi", "nostro",
    "nostra", "dopo", "prima", "altro",
    "altra", "sembra", "viene", "venne"
}

GENERICHE = {
    "omicidio", "assassino", "ucciso",
    "morto", "scomparso", "scomparsa",
    "madre", "padre", "figlia", "figlio",
    "famiglia", "marito", "moglie",
    "bambino", "bambini", "scuola",
    "prigione", "agghiacciante",
    "segreto", "lotteria", "matrimonio",
    "anni", "giorni", "delitto",
    "vittima", "polizia", "indagine",
    "criminale", "orrore", "mistero",
    "tragico", "terribile", "ragazzo",
    "ragazza", "donna", "uomo"
}

# Dizionario bilingue: entrambi i titoli
# vengono convertiti nella stessa forma.

TRADUZIONI = {
    "murder": "omicidio",
    "murdered": "omicidio",
    "killer": "assassino",
    "killed": "ucciso",
    "death": "morte",
    "dead": "morto",
    "missing": "scomparsa",
    "disappeared": "scomparsa",
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
    "children": "bambini",
    "monster": "mostro",
    "butcher": "macellaio",
    "sniper": "cecchino",
    "massacre": "massacro",
    "nightmare": "incubo",
    "chatbot": "chatbot",
    "pushed": "spinto",
    "push": "spinto",
    "message": "messaggio",
    "last": "ultimo",
    "final": "ultimo",
    "courage": "coraggio",
    "revenge": "vendetta",
    "river": "fiume",
    "mystery": "mistero",
    "horror": "orrore",
    "horrors": "orrore",
    "twins": "gemelle",
    "twin": "gemelle",
    "clown": "clown",
    "ponzi": "ponzi",
    "truth": "verita",
    "waking": "aperto",
    "night": "notte",
    "found": "ritrovato",
    "vanished": "scomparsa",
    "lost": "scomparsa",
    "strange": "strano",
    "shocking": "scioccante",
    "absurd": "assurdo",
    "disturbing": "inquietante",
    "twisted": "distorta",
    "mind": "mente",
    "life": "vita",
    "lives": "vita",
    "double": "doppia",
    "scheme": "schema",
    "crime": "crimine",
    "crimes": "crimine",
    "youngest": "giovane",
    "sentenced": "condannata",
    "cremated": "cremata",
    "cremate": "cremata",
    "fienile": "fienile",
    "barn": "fienile",
    "rostov": "rostov",
    "udine": "udine",
    "farmville": "farmville",
    "pistorius": "pistorius"
}

# Alcuni titoli usano grafie alternative.
# Le correzioni riguardano parole riconoscibili,
# non l'intero testo.

CORREZIONI = {
    "mass4cro": "massacro",
    "mass4cre": "massacro",
    "k1ller": "killer",
    "k!ller": "killer",
    "mister0": "mistero",
    "incub0": "incubo",
    "0rr0re": "orrore",
    "sсhabusiness": "schabusiness"
}


def normalizza(testo):
    testo = str(testo or "").lower()

    # Caratteri stilizzati frequenti
    testo = testo.replace("Ǝ", "e").replace("ǝ", "e")
    testo = testo.replace("∀", "a")
    testo = testo.replace("Я", "r").replace("я", "r")
    testo = testo.replace("с", "c")

    for originale, corretto in CORREZIONI.items():
        testo = testo.replace(originale, corretto)

    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(
        carattere for carattere in testo
        if not unicodedata.combining(carattere)
    )

    # Ricostruisce parole con lettere sostituite
    testo = re.sub(r"\bk\s*!\s*ller\b", "killer", testo)
    testo = re.sub(r"\bk\s*1\s*ller\b", "killer", testo)

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
    match = re.search(
        r"\b(?:pt|part|parte)\s*([1-9])\b",
        normalizza(titolo)
    )
    return int(match.group(1)) if match else None


def leggi_json(percorso):
    with percorso.open("r", encoding="utf-8") as file:
        return json.load(file)


def peso_parola(parola, frequenze, totale):
    frequenza = frequenze.get(parola, 0)
    return math.log(1 + totale / (1 + frequenza))


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

    comuni_descrizione = (
        parole_descrizione & parole_video
    ) - comuni_titolo

    specifiche_titolo = comuni_titolo - GENERICHE
    specifiche_descrizione = (
        comuni_descrizione - GENERICHE
    )

    # Le parole generiche pesano meno.
    punteggio_titolo = sum(
        peso_parola(p, frequenze, totale_video)
        * (0.35 if p in GENERICHE else 1.0)
        for p in comuni_titolo
    )

    # Descrizione: contributo ridotto
    # e limitato a un massimo.
    punteggio_descrizione = sum(
        peso_parola(p, frequenze, totale_video)
        for p in specifiche_descrizione
    )

    punteggio_descrizione = min(
        punteggio_descrizione * 0.15,
        1.5
    )

    punteggio = (
        punteggio_titolo + punteggio_descrizione
    )

    if len(specifiche_titolo) >= 2:
        punteggio += 2.0

    # Premia una corrispondenza molto rara,
    # senza renderla automaticamente sicura.
    parole_rare = [
        p for p in specifiche_titolo
        if frequenze.get(p, 0) <= 2
    ]

    if parole_rare:
        punteggio += 1.0

    return {
        "score": round(punteggio, 3),
        "common": sorted(
            comuni_titolo | comuni_descrizione
        ),
        "title_matches": len(specifiche_titolo),
        "description_matches": len(
            specifiche_descrizione
        ),
        "rare_matches": len(parole_rare)
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
            parole_importanti(
                elemento.get("title", "")
            )
        )

    risultati = []

    for episodio in episodi:
        titolo = episodio.get("titolo", "")
        descrizione = episodio.get("descrizione", "")
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

            parte_apple = numero_parte(titolo)
            parte_video = numero_parte(titolo_video)

            # Blocca parti differenti quando
            # entrambe sono esplicitamente indicate.
            if (
                parte_apple is not None
                and parte_video is not None
                and parte_apple != parte_video
            ):
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

            # Se una sola parte e' indicata,
            # la corrispondenza resta incerta.
            if (
                parte_apple is not None
                and parte_video is None
            ) or (
                parte_apple is None
                and parte_video is not None
            ):
                analisi["parte_incerta"] = True
            else:
                analisi["parte_incerta"] = False

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

            # Una corrispondenza forte richiede:
            # - almeno due parole specifiche,
            #   oppure una rara con punteggio alto
            # - distanza sufficiente dal secondo
            # - nessuna incertezza sulla parte
            forte_per_parole = (
                primo["title_matches"] >= 2
                or (
                    primo["title_matches"] >= 1
                    and primo["rare_matches"] >= 1
                    and primo["score"] >= 5.0
                )
            )

            if (
                forte_per_parole
                and primo["score"] >= 5.0
                and not primo["parte_incerta"]
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

    # Non considera forti due episodi
    # associati allo stesso video.
    utilizzi = defaultdict(list)

    for risultato in risultati:
        if (
            risultato["status"] == "CANDIDATO_FORTE"
            and risultato["candidates"]
        ):
            url = risultato["candidates"][0]["url"]
            utilizzi[url].append(risultato)

    for associati in utilizzi.values():
        if len(associati) > 1:
            for risultato in associati:
                risultato["status"] = "DA_VERIFICARE"

    forti = sum(
        risultato["status"] == "CANDIDATO_FORTE"
        for risultato in risultati
    )

    gia_collegati = sum(
        str(risultato["trackId"]) in catalogo
        for risultato in risultati
    )

    print("MERON - CONTROLLO MIGLIORATO")
    print("Episodi Apple:", len(episodi))
    print("Video YouTube:", len(video))
    print("Candidati forti:", forti)
    print("Da verificare:", len(risultati) - forti)
    print("Episodi gia' nel catalogo:", gia_collegati)

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

    print("Creato controllo_video_meron.json")


if __name__ == "__main__":
    controlla()
