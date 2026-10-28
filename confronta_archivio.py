
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



# MERON - controllo combinato con dizionari originali integrali

def numero_parte(titolo):
    m = re.search(r'\b(?:pt|part|parte)\s*([1-9])\b', normalizza(titolo))
    return int(m.group(1)) if m else None


def punteggio_base(titolo, descrizione, titolo_video, frequenze, totale):
    titolo_parole = parole_importanti(titolo)
    video_parole = parole_importanti(titolo_video)
    comuni_titolo = titolo_parole & video_parole
    comuni_descrizione = (parole_importanti(descrizione) & video_parole) - comuni_titolo
    specifiche = comuni_titolo - GENERICHE
    descr_specifiche = comuni_descrizione - GENERICHE
    def peso(p):
        return math.log(1 + totale / (1 + frequenze.get(p, 0)))
    score = sum(peso(p) * (0.35 if p in GENERICHE else 1) for p in comuni_titolo)
    score += min(sum(peso(p) for p in descr_specifiche) * 0.15, 1.5)
    if len(specifiche) >= 2:
        score += 2
    rare = [p for p in specifiche if frequenze.get(p, 0) <= 2]
    if rare:
        score += 1
    return {'score': round(score, 3), 'common': sorted(comuni_titolo | comuni_descrizione),
            'title_matches': len(specifiche), 'description_matches': len(descr_specifiche),
            'rare_matches': len(rare), 'rare_words': sorted(rare)}


def bonus_nomi_specifici(titolo_apple, titolo_video, frequenze):
    """Bonus di ordinamento, non di classificazione: riconosce il soggetto del titolo.

    Nei titoli Apple la parte iniziale dopo "Ep. N:" e spesso il nome del caso.
    Una coincidenza in questa posizione vale piu di parole generiche come
    "scomparsa" o "nulla". Non deduce nomi da maiuscole arbitrarie.
    """
    pulito = re.sub(r"^\s*ep\.?\s*\d+\s*[:.\-]?\s*", "", str(titolo_apple), flags=re.I)
    # Titolo prima del sottotitolo, normalmente il nome del caso.
    intestazione = re.split(r"\s*[:,;–—]\s*", pulito, maxsplit=1)[0]
    parole_intestazione = list(dict.fromkeys(normalizza(intestazione).split()))
    parole_video = parole_importanti(titolo_video)
    parole_apple = parole_importanti(titolo_apple)

    # Solo parole distintive; non assegniamo un bonus per "nulla", "anni", ecc.
    escluse = GENERICHE | {"nulla", "vita", "caso", "storia", "vero", "falso", "sparita", "scomparsa"}
    centrali = [p for p in parole_intestazione[:4]
               if len(p) >= 4 and p not in STOPWORDS and p not in escluse]
    corrispondenze = [p for p in centrali if p in parole_video]

    bonus = 0.0
    if corrispondenze:
        # Forte priorita al soggetto del caso, anche quando coincide solo il nome.
        bonus += 7.0 + 3.0 * (len(corrispondenze) - 1)

    altre = (parole_apple & parole_video) - set(centrali) - escluse
    bonus += min(1.0 * sum(frequenze.get(p, 0) <= 3 for p in altre), 2.0)
    return bonus


def carica_modello():
    try:
        from sentence_transformers import SentenceTransformer
        print('Caricamento controllo bilingue...')
        return SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')
    except Exception as exc:
        print('Modello bilingue non disponibile; uso il confronto parole:', str(exc)[:160])
        return None


def controlla():
    with FILE_APPLE.open(encoding='utf-8') as f:
        episodi = json.load(f)['episodes']
    with FILE_YOUTUBE.open(encoding='utf-8') as f:
        video = json.load(f)['videos']
    with FILE_CATALOGO.open(encoding='utf-8') as f:
        catalogo = json.load(f)['videos']
    if not isinstance(episodi, list) or not isinstance(video, list) or not isinstance(catalogo, dict):
        raise ValueError('Formato JSON non valido')
    video = [v for v in video if isinstance(v.get('url'), str) and v['url'].startswith('https://www.youtube.com/watch?v=')]
    frequenze = Counter()
    for v in video:
        frequenze.update(parole_importanti(v.get('title', '')))

    # Secondo controllo bilingue: NON sostituisce i risultati del motore precedente.
    modello = carica_modello()
    similarita = None
    if modello is not None and episodi and video:
        import numpy as np
        titoli = [e.get('titolo', '') for e in episodi] + [v.get('title', '') for v in video]
        vettori = modello.encode(titoli, normalize_embeddings=True, show_progress_bar=False)
        similarita = np.asarray(vettori[:len(episodi)]) @ np.asarray(vettori[len(episodi):]).T

    risultati = []
    for i, episodio in enumerate(episodi):
        titolo = episodio.get('titolo', '')
        descrizione = episodio.get('descrizione', '')
        candidati = []
        for j, v in enumerate(video):
            titolo_video = v.get('title', '')
            parte_a, parte_y = numero_parte(titolo), numero_parte(titolo_video)
            if parte_a is not None and parte_y is not None and parte_a != parte_y:
                continue
            analisi = punteggio_base(titolo, descrizione, titolo_video, frequenze, len(video))
            sem = float(similarita[i, j]) if similarita is not None else 0.0
            # Per 'da verificare' basta un indizio lessicale O semantico.
            if not analisi['common'] and sem < 0.40:
                continue
            parte_incerta = (parte_a is None) != (parte_y is None)
            # Lo score originale rimane invariato: non perdiamo i candidati forti precedenti.
            analisi.update({'title': titolo_video, 'url': v['url'],
                            'similarity': round(sem, 3) if similarita is not None else None,
                            'parte_incerta': parte_incerta,
                            'ranking_score': round(analisi['score'] + max(0, sem - 0.40) * 3, 3)})
            candidati.append(analisi)

        # La decisione 'forte' usa gli stessi criteri del codice ripristinato.
        candidati_base = sorted(candidati, key=lambda c: c['score'], reverse=True)
        stato = 'DA_VERIFICARE' if candidati else 'NESSUNA_CORRISPONDENZA'
        migliore = candidati_base[0] if candidati_base else None
        if migliore:
            secondo = candidati_base[1]['score'] if len(candidati_base) > 1 else 0
            forte = (migliore['title_matches'] >= 2 or
                     (migliore['title_matches'] >= 1 and migliore['rare_matches'] >= 1 and migliore['score'] >= 5))
            if (forte and migliore['score'] >= 5 and not migliore['parte_incerta'] and
                    (secondo == 0 or migliore['score'] > secondo * 1.5)):
                stato = 'CANDIDATO_FORTE'
        # Se e' forte, teniamo al primo posto il candidato valutato dal vecchio algoritmo.
        # Negli altri casi mostriamo 5 proposte ordinate usando anche il modello bilingue.
        if stato == 'CANDIDATO_FORTE':
            altri = sorted((c for c in candidati if c is not migliore),
                           key=lambda c: c['ranking_score'], reverse=True)
            migliori = [migliore] + altri[:4]
        else:
            migliori = sorted(
                candidati,
                key=lambda c: (
                    c['ranking_score'] + bonus_nomi_specifici(
                        titolo, c['title'], frequenze
                    ),
                    c['ranking_score']
                ),
                reverse=True
            )[:5]
        risultati.append({'trackId': episodio.get('id'), 'episode': titolo,
                          'status': stato, 'candidates': migliori})

    utilizzi = defaultdict(list)
    for r in risultati:
        if r['status'] == 'CANDIDATO_FORTE' and r['candidates']:
            utilizzi[r['candidates'][0]['url']].append(r)
    for gruppo in utilizzi.values():
        if len(gruppo) > 1:
            for r in gruppo:
                r['status'] = 'DA_VERIFICARE'

    forti = sum(r['status'] == 'CANDIDATO_FORTE' for r in risultati)
    senza = sum(r['status'] == 'NESSUNA_CORRISPONDENZA' for r in risultati)
    nuovi = sum(r['status'] == 'CANDIDATO_FORTE' and str(r['trackId']) not in catalogo for r in risultati)
    print('MERON - CONTROLLO COMBINATO')
    print('Episodi Apple:', len(episodi))
    print('Video YouTube:', len(video))
    print('Candidati forti:', forti)
    print('Nuovi candidati forti:', nuovi)
    print('Da verificare:', len(risultati) - forti - senza)
    print('Nessuna corrispondenza:', senza)
    print('Episodi gia nel catalogo:', sum(str(r['trackId']) in catalogo for r in risultati))
    with FILE_RISULTATI.open('w', encoding='utf-8') as f:
        json.dump({'results': risultati}, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('Creato controllo_video_meron.json')
    print('videos.json non modificato')


if __name__ == '__main__':
    controlla()
