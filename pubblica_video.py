import json
import os
import re
import subprocess
import sys
import tempfile
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# Conserva e riutilizza tutti i dizionari del programma gia installato.
from confronta_archivio import GENERICHE, STOPWORDS, TRADUZIONI

BASE = Path(__file__).resolve().parent
# V5: pubblica automaticamente i collegamenti che superano i filtri.
# Per fare una simulazione, imposta MERON_SIMULAZIONE=1 nel workflow.
PUBBLICA = False  # V7: simulazione; NON cambia videos.json
CERCA_ITALIANO = os.environ.get("MERON_TITOLI_ITALIANI", "1") != "0"
CHANNEL_ID = "UCxH0MkY6v0sjZzmMgW9TSRQ"

# Integrazioni ai dizionari esistenti, non loro sostituzioni.
TRAD = dict(TRADUZIONI)
TRAD.update({
    "new": "nuova", "latest": "nuova", "truth": "verita",
    "happened": "successo", "happens": "successo", "that": "quella",
    "night": "notte", "macabre": "macabro", "plan": "piano",
    "twins": "gemelle", "twin": "gemelle", "cult": "setta",
    "zizians": "ziziani", "gypsy": "gipsy", "scheme": "schema",
    "secrets": "segreti", "personalities": "personalita",
    "freeway": "superstrada", "phantom": "fantasma",
    "hiding": "nascondeva", "wanted": "voleva", "ice": "ghiaccio",
    "lady": "donna", "whole": "tutta", "dark": "oscuro",
    "side": "lato", "sides": "lato", "light": "luce",
    "killers": "assassini", "monster": "mostro", "butcher": "macellaio",
    "sniper": "cecchino", "massacre": "massacro", "barn": "fienile",
    "letters": "lettere", "books": "libri", "lies": "bugie",
    "other": "altre", "death": "morte", "pushed": "spinto",
    "courage": "coraggio", "last": "ultimo", "message": "messaggio",
    "everything": "tutto", "seemed": "sembrava", "decided": "deciso",
    "already": "gia",
})
# Queste parole vengono conservate: distinguono aggiornamenti e casi.
STOP = (set(STOPWORDS) - {"elisa", "nuova", "new", "truth", "verita",
        "notte", "successo", "morte", "giorni", "ed"}) | set("""
for of to at on by is was are be it its his her she he my your our has had
an as but out all you us we they them nel al ai ad sul tra fra ha ho
si non mi ti ci vi piu gia sia ep pt jr this that what which cos lei noi
""".split())
DESCRITTIVE = set(GENERICHE) | {k for k, v in TRAD.items() if k != v} | {v for k, v in TRAD.items() if k != v} | set("""
lato oscuro luce nulla niente davvero siamo stati fatto fine vita mondo
caso casi storia storie racconti puntata puntate nuovo nuove nuovi
serial made italiani mediatici dietro sempre ultimo ultima ultime vero
falsa falso mistero mostro tragedia assurdo assurda scioccante incredibile
famoso famosi scompare ritrovato scomparsa morte giorno giorni anno anni
suo suoi loro mamma uomo donna piccolo piccola bambini amica amante
assassina assassino crimine delitto verita nuova quella notte successo
orrore inquietante terribile misterioso misteriosi nascosto nascosta
profondo grande prima dopo durante soltanto solo mente dentro fuori
setta sparizione schiava vittima vittime morte morto morta ucciso uccisa
shot mr mrs full entire complete crimes bambini bambine proprio stessa
aggiornamento update inedito intervista con senza vita segreti segreto
famiglia famigliare celebrity edition supersnatural supernatural
""".split())
PART_RE = re.compile(r"\b(?:pt|part|parte)\s*(\d+|viii|vii|vi|iv|iii|ii|v|i)\b")


def leggi(nome):
    with (BASE / nome).open(encoding="utf-8-sig") as f:
        dati = json.load(f)
    if not isinstance(dati, dict):
        raise ValueError(f"Formato non valido: {nome}")
    return dati


def salva(nome, dati):
    destinazione = BASE / nome
    contenuto = json.dumps(dati, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temporaneo = None
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=BASE,
                                         suffix=".tmp", delete=False) as f:
            temporaneo = Path(f.name)
            f.write(contenuto)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporaneo, destinazione)
    finally:
        if temporaneo is not None and temporaneo.exists():
            temporaneo.unlink()


def video_id(url):
    if not isinstance(url, str):
        return None
    try:
        p = urlparse(url)
        if p.scheme != "https":
            return None
        if p.netloc in {"www.youtube.com", "youtube.com", "m.youtube.com"} and p.path == "/watch":
            valori = parse_qs(p.query).get("v", [])
            v = valori[0] if len(valori) == 1 else ""
        elif p.netloc == "youtu.be":
            v = p.path.lstrip("/")
        else:
            return None
        return v if re.fullmatch(r"[A-Za-z0-9_-]{11}", v) else None
    except ValueError:
        return None


def normalizza(testo):
    testo = str(testo or "")

    # Corregge una l minuscola usata come I dentro una parola
    # quasi tutta maiuscola, prima di perdere questa informazione.
    def correggi_i_stilizzata(match):
        parola = match.group(0)
        resto = parola.replace("l", "")
        if (
            "l" in parola
            and len(resto) >= 4
            and resto.isupper()
            and all(c.isupper() for c in resto if c.isalpha())
        ):
            return parola.replace("l", "I")
        return parola

    testo = re.sub(r"[^\W\d_]+", correggi_i_stilizzata, testo)
    testo = testo.casefold()
    testo = testo.translate(str.maketrans({
        "\u01dd": "e", "\u018e": "e", "\u2200": "a",
        "\u044f": "r", "\u0441": "c", "\u0438": "n",
        "\u043e": "o", "\u0430": "a",
    }))

    # Mantiene tutte le correzioni specifiche gia presenti.
    for originale, corretto in {
        "k!ller": "killer", "l!sa": "lisa",
        "c!rce0": "circeo", "assasslna": "assassina",
        "madlson": "madison"
    }.items():
        testo = testo.replace(originale, corretto)

    testo = unicodedata.normalize("NFKD", testo)
    testo = "".join(
        c for c in testo if not unicodedata.combining(c)
    )

    # Il punto esclamativo vale I solo DENTRO una parola.
    testo = re.sub(r"(?<=[a-z])!(?=[a-z])", "i", testo)

    def correggi_cifre(match):
        parola = match.group(0)
        # Non altera 764, 105, gli anni o sigle come PT10.
        if parola.isdigit() or re.fullmatch(
            r"(?:pt|part|parte|ep)\d+", parola
        ):
            return parola
        if re.search(r"[a-z]", parola):
            return parola.translate(str.maketrans({
                "0": "o", "4": "a", "3": "e"
            }))
        return parola

    # Include anche lo zero INIZIALE: 0DI0 diventa odio.
    testo = re.sub(r"\b[a-z0-9]+\b", correggi_cifre, testo)
    testo = re.sub(
        r"\b([a-z])\.\s*([a-z])(?:\.(?=\W|$)|\b)",
        r"\1\2", testo
    )
    testo = re.sub(r"[^a-z0-9 ]", " ", testo)
    return re.sub(r"\s+", " ", testo).strip()

def dettagli(titolo):
    testo = re.sub(r"^\s*(?:ep|episodio|episode)\s*\.*\s*\d+\s*[:.\-]?\s*",
                   "", str(titolo or ""), flags=re.I)
    testo = re.sub(r"\s*[|\-]\s*Elisa True Crime\s*$", "", testo, flags=re.I)
    testo = normalizza(testo)
    testo = re.sub(r"\bvanished without a trace\b", "scomparsa nel nulla", testo)
    parti = PART_RE.findall(testo)
    romani = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8}
    parte = int(parti[0]) if parti and parti[0].isdigit() else romani.get(parti[0]) if parti else None
    corpo = PART_RE.sub(" ", testo)
    lista = [p for p in corpo.split() if p not in STOP and len(p) >= 2]
    termini = {TRAD.get(p, p) for p in lista} - STOP
    indizi = {p for p in lista if p not in DESCRITTIVE and not p.isdigit()}
    aggiornamento = bool(re.search(r"\b(?:aggiornamento|update|updates)\b|\bnew truth\b|\bnuova verita\b", testo))
    return {"testo": testo, "termini": termini, "indizi": indizi,
            "parte": parte, "aggiornamento": aggiornamento,
            "trailer": "trailer" in corpo.split()}


def titoli_italiani(archivio):
    if not CERCA_ITALIANO:
        return "DISATTIVATO", 0
    comando = [sys.executable, "-m", "yt_dlp", "--ignore-config",
        "--flat-playlist", "--skip-download", "--dump-single-json",
        "--socket-timeout", "10", "--retries", "1", "--extractor-retries", "1",
        "--extractor-args", "youtube:lang=it",
        f"https://www.youtube.com/channel/{CHANNEL_ID}/videos"]
    try:
        r = subprocess.run(comando, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        if r.returncode:
            raise RuntimeError(r.stderr[-300:])
        dati = json.loads(r.stdout)
        if dati.get("channel_id") and dati["channel_id"] != CHANNEL_ID:
            raise ValueError("Canale inatteso")
        entrate = dati.get("entries")
        if not isinstance(entrate, list) or not entrate:
            raise ValueError("Elenco vuoto")
        nuovi = 0
        for v in entrate:
            if not isinstance(v, dict) or v.get("id") not in archivio:
                continue
            titolo = v.get("title")
            if isinstance(titolo, str) and titolo.strip() and titolo not in archivio[v["id"]]["titoli"]:
                archivio[v["id"]]["titoli"].append(titolo)
                nuovi += 1
        return "RIUSCITO_TITOLI_NON_GARANTITI_IN_ITALIANO", nuovi
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print("Titoli in italiano non recuperati; uso l'archivio disponibile:", str(exc)[:250])
        return "NON_DISPONIBILE", 0


def valuta(a, b, titolo, vid):
    comuni = a["termini"] & b["termini"]
    indizi = a["indizi"] & b["indizi"]
    cop_a = len(comuni) / len(a["termini"]) if a["termini"] else 0
    cop_b = len(comuni) / len(b["termini"]) if b["termini"] else 0
    livello, regola = 0, "Indizi insufficienti"
    if a["testo"] == b["testo"] and len(a["testo"].split()) >= 3:
        livello, regola = 4, "Titolo completo coincidente"
    elif a["termini"] == b["termini"] and len(comuni) >= 2 and (indizi or any(x.isdigit() for x in comuni)):
        livello, regola = 3, "Titoli equivalenti con nomi o numeri distintivi"
    elif len(indizi) >= 2 and min(cop_a, cop_b) >= 0.35:
        livello, regola = 2, "Almeno due indizi distintivi e contesto coerente"
    elif indizi and len(comuni) >= 3 and min(cop_a, cop_b) >= 0.75:
        livello, regola = 2, "Indizio distintivo e forte copertura bilingue"
    # La descrizione aggiunge indizi solo se un riferimento coincide gia nel titolo.
    supporto = a.get("descr_indizi", set()) & b["indizi"]
    if livello < 2 and indizi and len(indizi | supporto) >= 2 and b["indizi"] <= (indizi | supporto):
        livello, regola = 2, "Riferimento nel titolo confermato dalla descrizione Apple"
    # La stessa storia non prova la corrispondenza della singola parte.
    blocchi = []
    if a["trailer"] or b["trailer"]:
        blocchi.append("TRAILER")
    if a["parte"] != b["parte"]:
        blocchi.append("PARTI_NON_ALLINEATE")
    if a["aggiornamento"] != b["aggiornamento"]:
        blocchi.append("VERSIONI_DIVERSE")
    return {"videoId": vid, "title": titolo,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "livello": livello, "regola": regola, "blocchi": blocchi,
        "indizi": sorted(indizi), "comuni": sorted(comuni),
        "copertura": round(min(cop_a, cop_b), 3),
        "priorita": (livello, len(indizi), round(min(cop_a, cop_b), 3), len(comuni))}



def chiave_caso_condiviso(titolo):
    """Identifica lo stesso caso ignorando soltanto PT.1 e PT.2."""
    info = dettagli(titolo)
    base = PART_RE.sub(" ", info["testo"])
    return re.sub(r"\s+", " ", base).strip(), info["parte"]


def collega_video_del_caso(esiti, usati, archivio):
    """Permette UN video sul caso per entrambe le parti, con criteri precisi.

    Non afferma che il video copra integralmente entrambe le puntate.
    Blocca i video che riportano un numero di parte esplicito.
    """
    gruppi = defaultdict(list)
    gia_assegnati = {
        voce["selezionato"]["videoId"]
        for voce in esiti
        if voce["esito"] == "SELEZIONATO" and voce["selezionato"]
    }

    for voce in esiti:
        if voce["esito"] != "PARTI_NON_ALLINEATE":
            continue
        caso, numero_parte = chiave_caso_condiviso(voce["episode"])
        if caso and numero_parte in (1, 2):
            gruppi[caso].append((numero_parte, voce))

    proposte_coppie = []
    for caso, gruppo in gruppi.items():
        if len(gruppo) != 2 or {p for p, _ in gruppo} != {1, 2}:
            continue
        gruppo.sort(key=lambda e: e[0])
        prima, seconda = gruppo[0][1], gruppo[1][1]
        candidati = []
        for episodio in (prima, seconda):
            opzioni = episodio.get("proposte", [])
            if not opzioni or not isinstance(opzioni[0], dict):
                break
            migliore = opzioni[0]
            # Deve essere l'unico video con sufficiente supporto per il caso.
            if (migliore.get("livello", 0) < 2
                    or migliore.get("blocchi") != ["PARTI_NON_ALLINEATE"]
                    or len(migliore.get("indizi", [])) < 2
                    or any(
                        x.get("livello", 0) >= migliore["livello"]
                        and x.get("videoId") != migliore.get("videoId")
                        for x in opzioni[1:] if isinstance(x, dict)
                    )):
                break
            candidati.append(migliore)
        if len(candidati) != 2:
            continue
        a, b = candidati
        vid = a.get("videoId")
        if (not vid or vid != b.get("videoId") or vid not in archivio
                or vid in usati or vid in gia_assegnati
                or dettagli(a.get("title", ""))["parte"] is not None
                or dettagli(b.get("title", ""))["parte"] is not None):
            continue
        proposte_coppie.append((vid, prima, seconda, a, b))

    # Lo stesso video non puo essere usato per due CASI diversi.
    contatore = Counter(vid for vid, *_ in proposte_coppie)
    aggiunte = 0
    for vid, prima, seconda, a, b in proposte_coppie:
        if contatore[vid] != 1:
            continue
        for episodio, candidato in ((prima, a), (seconda, b)):
            episodio["esito"] = "VIDEO_DEL_CASO_CONDIVISO"
            episodio["selezionato"] = candidato
            episodio["sharedCaseVideo"] = True
            # Confermato dall'utente per Gacy; sugli altri e' una proposta.
            episodio["sharedCoverageConfirmed"] = (vid == "NGnCtty6flw")
            aggiunte += 1
    return aggiunte // 2


# V5: riconosce titoli diversi con un soggetto raro condiviso.
# Non si affida a parole genericamente associate al true crime.
ANCORA_NON_SICURA = set("""
madre padre figlia figlio famiglia bimbo bambini bambino donna uomo esperimento
clown killer assassino assassina storie storia scomparsa scomparso
orrore incubo mistero vittima morte delitto crimine rapito rubata
star famoso famiglia timido spietato scena scuola guerra
soldi finale video incredibile quel quella questo questa niente
la notte episodio indagine anni giorni strage tragico
questo primavera intervista esclusiva
""".split())


def testo_con_alias(testo):
    t = normalizza(testo)
    # Alias contestuali, NON sostituzioni arbitrarie di nomi.
    t = re.sub(r"\blady di\b", "lady diana", t)
    t = re.sub(r"\bjung yoo jung\b", "jung yoojung", t)
    t = re.sub(r"\byoo jung\b", "yoojung", t)
    t = re.sub(r"\bray rivera\b", "rey rivera", t)
    return t


def informazioni_v5(testo):
    normale = dettagli(testo)
    alias = testo_con_alias(normale['testo'])
    # Nuove parole solo nei casi di alias effettivamente rilevati.
    parole = alias.split()
    termini = set(normale['termini'])
    for p in parole:
        if p in ('yoojung', 'rey', 'rivera', 'diana'):
            termini.add(p)
    if 'ray' in termini and 'rey' in termini:
        termini.discard('ray')
    riferimenti = {p for p in termini if p not in DESCRITTIVE and p not in STOP
                   and p not in ANCORA_NON_SICURA and len(p) >= 4}
    return {**normale, 'testo_alias': alias,
            'termini_v5': termini, 'riferimenti_v5': riferimenti}


def contraddizione_nome(testo_apple, testo_video, parola):
    # Esempio: "Giovanna Comunale" NON e' "Joey Comunale".
    # Rileva la differenza quando in entrambe le fonti e' espresso
    # un nome immediatamente prima del cognome condiviso.
    def prima(testo):
        parole = testo_con_alias(testo).split()
        for pos, p in enumerate(parole):
            if p == parola and pos >= 1:
                precedente = parole[pos-1]
                if (len(precedente) >= 3 and precedente not in STOP
                        and precedente not in DESCRITTIVE
                        and precedente not in {'the', 'del', 'della', 'dello', 'di', 'la', 'le',
                                                'a', 'caso', 'story', 'storia', 'famiglia', 'casa'}):
                    return precedente
        return None
    a, b = prima(testo_apple), prima(testo_video)
    return bool(a and b and a != b)


def valuta_ancore_v5(titolo_apple, titolo_video, videoid, frequenze):
    a = informazioni_v5(titolo_apple)
    b = informazioni_v5(titolo_video)

    if a['trailer'] or b['trailer'] or a['aggiornamento'] != b['aggiornamento']:
        return None
    if b['parte'] is not None and b['parte'] != a['parte']:
        return None

    comuni = a['termini_v5'] & b['termini_v5']
    if not comuni:
        return None
    ancore = a['riferimenti_v5'] & b['riferimenti_v5']
    rare = {p for p in ancore if len(frequenze.get(p, set())) == 1}
    if any(contraddizione_nome(titolo_apple, titolo_video, p) for p in rare):
        return None
    # "Jeffrey Dahmer" non deve diventare "Jeffrey Lundgren".
    ta = a['testo_alias'].split()
    tb = b['testo_alias'].split()
    if (len(ta) >= 2 and len(tb) >= 2
            and ta[0] == tb[0] and ta[0] not in STOP
            and ta[0] not in DESCRITTIVE
            and len(ta[0]) >= 4
            and ta[1] != tb[1]
            and len(ta[1]) >= 4 and len(tb[1]) >= 4
            and ta[1] not in DESCRITTIVE and tb[1] not in DESCRITTIVE
            and ta[1] not in STOP and tb[1] not in STOP
            and tb[1] not in {'must', 'should', 'could', 'would', 'will', 'does', 'do', 'did', 'have', 'has', 'was', 'were', 'had', 'not', 'never'}):
        return None

    parole_a = a['termini_v5']
    parole_b = b['termini_v5']
    perfetta = (parole_a == parole_b and len(comuni) >= 2)
    # Esempio Freeway Phantom -> Il Fantasma della Superstrada.
    bilingue_esatta = (perfetta and
                      any(len(frequenze.get(p,set())) == 1 for p in comuni if len(p) >= 5))
    # Solo quando i nomi sono davvero presenti in ENTRAMBI i titoli.
    due_nomi = len(rare) >= 2
    # Parola molto rara, chiaramente riferita al caso.
    titolo_b = b['testo_alias'].split()
    token_in_primo_piano = any(p in titolo_b[:4] or p in titolo_b[-2:] for p in rare)
    # Anche una frase citata puo costituire un segnale molto distintivo.
    frase_comune = False
    base_a = a['testo_alias']
    base_b = b['testo_alias']
    for n in range(4, min(8, len(base_a.split())) + 1):
        pa = base_a.split()
        if any(' '.join(pa[k:k+n]) in base_b
               for k in range(0, len(pa) - n + 1)):
            frase_comune = True
            break

    grado, motivo = 0, None
    if (a['testo_alias'] == b['testo_alias']
            and len(base_a.split()) >= 2):
        grado, motivo = 100, 'Titoli coincidenti dopo le correzioni'
    elif ("lady diana" in a['testo_alias'] and
          "lady diana" in b['testo_alias']):
        grado, motivo = 96, 'Alias riconosciuto: Lady Diana / Lady Di'
    elif bilingue_esatta:
        grado, motivo = 94, 'Titoli equivalenti dopo la traduzione' 
    elif due_nomi:
        grado, motivo = 92, 'Due riferimenti distintivi rari in comune'
    elif (rare and len(comuni) >= 2 and
          (len(comuni) / max(1, min(len(parole_a), len(parole_b)))) >= 0.6):
        grado, motivo = 86, 'Riferimento raro e contesto coerente'
    elif rare and token_in_primo_piano:
        grado, motivo = 81, 'Riferimento raro al centro del video'
    elif rare and frase_comune:
        grado, motivo = 80, 'Frase distintiva condivisa'
    elif (a['parte'] is not None and b['parte'] is None
          and len(titolo_b) <= 5
          and {'strage', 'massacro', 'delitto'} & parole_a
          and any(p in titolo_b[:3] and len(frequenze[p]) <= 3
                  and p not in ANCORA_NON_SICURA and p not in DESCRITTIVE
                  for p in (comuni & a['riferimenti_v5']))):
        grado, motivo = 79, 'Caso geografico specifico, video breve e focalizzato'

    # Una sola parola come "rubata", "clown" o "madre" non basta.
    if not grado:
        return None

    # Per evitare false associazioni di omonimi usiamo il controllo
    # delle identita' prima del punteggio (Giovanna != Joey Comunale).

    return {
        'videoId': videoid,
        'title': titolo_video,
        'url': 'https://www.youtube.com/watch?v=' + videoid,
        'livello': 2,
        'regola': 'V5: ' + motivo,
        'blocchi': ['PARTI_NON_ALLINEATE'] if a['parte'] != b['parte'] else [],
        'indizi': sorted(rare),
        'comuni': sorted(comuni),
        'copertura': round(len(comuni) / max(1, min(len(parole_a), len(parole_b))), 3),
        'priorita': (grado, len(rare), len(comuni), -len(parole_b)),
        'gradoV5': grado,
        'motivoV5': motivo,
    }


def recupera_ancore_v5(esiti, archivio, usati):
    """Aggiunge proposte V5 senza confondere persone o parti.

    Se lo stesso video e' proposto per entrambe le parti, pubblica
    solo se entrambe riconducono allo stesso caso.
    """
    frequenze = defaultdict(set)
    for vid, archivio_video in archivio.items():
        for titolo, _ in archivio_video['dettagli']:
            for token in informazioni_v5(titolo)['termini_v5']:
                frequenze[token].add(vid)

    gia_assegnati = {x['selezionato']['videoId'] for x in esiti
                     if x.get('selezionato')}
    possibili = defaultdict(list)

    for r in esiti:
        if r['esito'] not in ('DATI_INSUFFICIENTI', 'PARTI_NON_ALLINEATE'):
            continue
        titolo = r['episode']
        aa = informazioni_v5(titolo)
        if aa['trailer']:
            continue
        matches = []
        for vid, info in archivio.items():
            if vid in usati or vid in gia_assegnati:
                continue
            valutazioni = [valuta_ancore_v5(titolo, t, vid, frequenze)
                           for t, _ in info['dettagli']]
            valutazioni = [v for v in valutazioni if v]
            if valutazioni:
                matches.append(max(valutazioni, key=lambda v: v['priorita']))

        # Esclude candidati di parti specifiche non allineate.
        matches = [m for m in matches
                   if not m['blocchi'] or m['blocchi'] == ['PARTI_NON_ALLINEATE']]
        matches.sort(key=lambda x: x['priorita'], reverse=True)
        r['proposte_v5'] = matches[:5]
        if not matches:
            continue
        primo = matches[0]
        # Non pubblica in caso di pareggio significativo fra due video.
        if len(matches) > 1 and matches[1]['gradoV5'] >= primo['gradoV5']:
            r['esito'] = 'V5_AMBIGUO'
            continue
        possibili[primo['videoId']].append((r, primo))

    aggiunti = 0
    for vid, gruppo in possibili.items():
        if len(gruppo) == 1:
            r, c = gruppo[0]
            if c['blocchi']:
                # Parte dichiarata senza prova della parte su YouTube:
                # attendere la coppia dello stesso caso.
                continue
            r['esito'] = 'V5_CORRISPONDENZA'
            r['selezionato'] = c
            r['sharedCaseVideo'] = False
            aggiunti += 1
            continue
        if len(gruppo) != 2:
            continue
        (a, ca), (b, cb) = gruppo
        pa = informazioni_v5(a['episode'])['parte']
        pb = informazioni_v5(b['episode'])['parte']
        if {pa, pb} != {1, 2}:
            continue
        # Entrambe devono parlare dello stesso caso e non solo
        # di una generica parola condivisa.
        ea = informazioni_v5(a['episode'])
        eb = informazioni_v5(b['episode'])
        nomi_comuni = (ea['riferimenti_v5'] & eb['riferimenti_v5'])
        if not nomi_comuni:
            continue
        if (ca['gradoV5'] < 79 or cb['gradoV5'] < 79):
            continue
        # Il video NON deve avere una parte numerata.
        if any(informazioni_v5(t)['parte'] is not None
               for t, _ in archivio[vid]['dettagli']):
            continue
        for r, c in gruppo:
            r['esito'] = 'V5_VIDEO_DEL_CASO_CONDIVISO'
            r['selezionato'] = c
            r['sharedCaseVideo'] = True
            r['sharedCoverageConfirmed'] = False
            aggiunti += 1
    return aggiunti



# V6: recupero prudente dei titoli abbreviati e dei nomi presenti
# nella descrizione Apple. Mantiene tutti i controlli V3-V5.
# Un caso documentato da fonti ufficiali: episodio e video parlano
# entrambi di Sierah Joughin, in Ohio nel 2016. Non usa titoli generici.
V6_CASI_DOCUMENTATI = {
    "1000773987869": ("7CwHU_RVO7s", "Stesso caso Sierah Joughin confermato dalle descrizioni pubbliche Apple e YouTube"),
}

V6_ESCLUSE = set(STOP) | set(DESCRITTIVE) | set("""
che cosa caso famiglia hanno fatto delle deglli della nello laltro
con from this that when where been quella quello anche affatto
storia queste questi della primo il gli lei lui loro loro ecco un uno una
then what happen happened really mystery little delling
""".split())


def titoli_v6(testo):
    # Allinea la stessa rimozione del numero Ep. della V5.
    return normalizza(re.sub(
        r"^\s*(?:ep|episodio|episode)\s*\.*\s*\d+\s*[:.\-]?\s*",
        "", str(testo or ""), flags=re.I
    ))


def recupera_descrizioni_v6(esiti, archivio, usati, episodi):
    """Seleziona solo evidenze specifiche; le altre restano da rivedere.

    Le descrizioni arrivano da episodi_apple.json prodotto gia dal workflow.
    Non scarica singole pagine YouTube e non usa trascrizioni automatiche.
    """
    apple_per_id = {str(e.get('id')): e for e in episodi if isinstance(e, dict)}
    in_uso = set(usati)
    in_uso.update(
        r['selezionato']['videoId'] for r in esiti
        if isinstance(r.get('selezionato'), dict)
    )

    frequenze = Counter()
    for vid, item in archivio.items():
        tutte = set()
        for titolo, _ in item['dettagli']:
            tutte.update(titoli_v6(titolo).split())
        frequenze.update(tutte)

    proposte = defaultdict(list)
    for r in esiti:
        if r.get('esito') != 'DATI_INSUFFICIENTI':
            continue
        apple = apple_per_id.get(str(r.get('trackId')))
        if not apple:
            continue
        titolo = titoli_v6(apple.get('titolo', ''))
        descrizione = normalizza(apple.get('descrizione', ''))
        parole_titolo = set(titolo.split())
        parole_descrizione = set(descrizione.split())
        possibili = []
        for vid, item in archivio.items():
            if vid in in_uso:
                continue
            # Non associare un titolo senza parte a un video PT.1/PT.2.
            if any(b['parte'] is not None for _, b in item['dettagli']):
                continue
            alternative = []
            for titolo_video, video_info in item['dettagli']:
                if video_info['trailer']:
                    continue
                ty = titoli_v6(titolo_video)
                parole_video = ty.split()
                tokens = set(parole_video)
                comuni_rari = {
                    w for w in tokens & parole_descrizione
                    if len(w) >= 4 and w not in V6_ESCLUSE
                    and frequenze[w] <= 3
                }
                condivisi_titolo = comuni_rari & parole_titolo

                grado, ragione = 0, ''
                evidenze = []
                if str(r['trackId']) in V6_CASI_DOCUMENTATI:
                    atteso, motivazione = V6_CASI_DOCUMENTATI[str(r['trackId'])]
                    if vid == atteso:
                        grado, ragione = 100, motivazione
                        evidenze = ['sierah', 'joughin']
                if not grado and len(parole_video) >= 5:
                    # Frase narrativa lunga condivisa letteralmente,
                    # come "che fine hanno fatto le gemelle".
                    if ' '.join(parole_video) in titolo:
                        note = {w for w in tokens & parole_titolo
                                if len(w) >= 5 and w not in STOP and w not in {'storia', 'video', 'episodio', 'podcast'}}
                        if note:
                            grado, ragione = 95, 'Frase distintiva del titolo YouTube contenuta nel titolo Apple'
                            evidenze = sorted(note)
                if (not grado and len(comuni_rari) >= 2
                        and condivisi_titolo and descrizione):
                    # Nomi presenti in una descrizione Apple e almeno
                    # uno anche nel titolo Apple. Per Skylar + Brooke,
                    # ad esempio, esclude il video su Skylar Neese.
                    grado, ragione = 90, 'Nomi distintivi condivisi tra titolo YouTube e descrizione Apple'
                    evidenze = sorted(comuni_rari)
                if grado:
                    alternative.append({
                        'videoId': vid,
                        'title': titolo_video,
                        'url': 'https://www.youtube.com/watch?v=' + vid,
                        'livello': 2,
                        'regola': 'V6: ' + ragione,
                        'blocchi': [], 'indizi': evidenze,
                        'comuni': evidenze,
                        'priorita': (grado, len(evidenze)),
                        'gradoV6': grado,
                        'confermaCopertura': False,
                    })
            if alternative:
                possibili.append(max(alternative, key=lambda v:v['priorita']))
        possibili.sort(key=lambda v:v['priorita'], reverse=True)
        r['proposte_v6'] = possibili[:5]
        if not possibili:
            continue
        if len(possibili) > 1 and possibili[0]['gradoV6'] <= possibili[1]['gradoV6']:
            r['esito'] = 'V6_AMBIGUO'
            continue
        proposte[possibili[0]['videoId']].append((r, possibili[0]))

    nuovi = 0
    for vid, gruppo in proposte.items():
        if len(gruppo) != 1:
            continue
        r, candidato = gruppo[0]
        if candidato['videoId'] in in_uso:
            continue
        r['esito'] = 'V6_CORRISPONDENZA'
        r['selezionato'] = candidato
        r['sharedCaseVideo'] = False
        in_uso.add(vid)
        nuovi += 1
    return nuovi

# V7: riavvicina le puntate Apple ai video ufficiali quando il caso
# e' identificato con un titolo DIVERSO. Nessun confronto per sole
# parole generiche e nessun video esterno ai 331 dell'archivio.
# Queste equivalenze sono state riscontrate su fonti pubbliche
# e accettate solo quando entrambi i titoli hanno i dati attesi.
V7_EQUIVALENZE = (
    {
        'apple': '1000655619715',
        'video': 'qw-zmbv1ZWE',
        'apple_tokens': ('elisa', 'claps'),
        'youtube_tokens': ('danilo', 'potenza'),
        'parte_apple': 2, 'parte_video': 2,
        'regola': 'Il video ufficiale su Danilo Restivo e PT.2; la descrizione rimanda esplicitamente a Elisa Claps PT.1',
    },
    {
        'apple': '1000678357033',
        'video': 'g4GCafibNTg',
        'apple_tokens': ('stephen', 'mcdaniels'),
        'youtube_tokens': ('lauren', 'giddings'),
        'parte_apple': None, 'parte_video': None,
        'regola': 'Il caso di Lauren Giddings riguarda Stephen McDaniel; il video ufficiale e incentrato sulla vittima',
    },
    {
        'apple': '1000725826007',
        'video': '4PtPjdraDqI',
        'apple_tokens': ('james', 'leininger'),
        'youtube_tokens': ('james',),
        'youtube_almeno_uno': ('precedente', 'previous'),
        'parte_apple': None, 'parte_video': None,
        'regola': 'La precedente vita del piccolo James e il caso di James Leininger, identificato anche nella descrizione Apple',
    },
)

# Proposte interessanti da segnalare nel report, SENZA pubblicare:
# titolo e argomento sono compatibili, ma mancano prove sulla
# corrispondenza editoriale esatta del video.
V7_DA_CONFERMARE = (
    ('1000706619630', 'EXkioJLq2xM',
     'Marlene Warren / Finita per mano di un clown: caso plausibile; da confermare con descrizione o contenuto del video'),
    ('1000680775583', 'G0r9GSLnXl4',
     'Simonetta Ferrero / Cosa e successo a Simonetta quel giorno: verificare che non sia un caso diverso di Simonetta'),
)


def recupera_casi_v7(esiti, archivio, usati):
    """Aggiunge solo 3 casi documentati, lasciando gli incerti nel report.

    Valida track ID, YouTube ID, soggetto e parti anche dopo future
    modifiche ai titoli. Non riutilizza video di altri episodi.
    """
    per_episodio = {r['trackId']: r for r in esiti}
    occupati = set(usati)
    occupati.update(
        r['selezionato']['videoId']
        for r in esiti
        if isinstance(r.get('selezionato'), dict)
    )
    nuovi = []
    for regola in V7_EQUIVALENZE:
        r = per_episodio.get(regola['apple'])
        vid = regola['video']
        if (not r or r.get('esito') not in
                ('DATI_INSUFFICIENTI', 'PARTI_NON_ALLINEATE')
                or vid not in archivio or vid in occupati):
            continue

        testo_apple = normalizza(r['episode'])
        info_apple = dettagli(r['episode'])
        if (not all(x in testo_apple.split() for x in regola['apple_tokens'])
                or info_apple['trailer']
                or info_apple['parte'] != regola['parte_apple']):
            continue

        possibili = []
        for titolo_youtube, info_video in archivio[vid]['dettagli']:
            yt = normalizza(titolo_youtube).split()
            if (all(x in yt for x in regola['youtube_tokens'])
                    and (not regola.get('youtube_almeno_uno')
                         or any(x in yt for x in regola['youtube_almeno_uno']))
                    and info_video['parte'] == regola['parte_video']
                    and not info_video['trailer']):
                possibili.append(titolo_youtube)
        if not possibili:
            continue

        titolo_youtube = max(possibili, key=len)
        candidato = {
            'videoId': vid,
            'title': titolo_youtube,
            'url': 'https://www.youtube.com/watch?v=' + vid,
            'livello': 2,
            'regola': 'V7: ' + regola['regola'],
            'blocchi': [],
            'indizi': sorted(regola['apple_tokens']),
            'comuni': [],
            'priorita': (99, 0, 0),
            'confermaCopertura': False,
        }
        r['esito'] = 'V7_CASO_DOCUMENTATO'
        r['selezionato'] = candidato
        r['sharedCaseVideo'] = False
        nuovi.append(vid)
        occupati.add(vid)

    da_confermare = []
    for eid, vid, motivo in V7_DA_CONFERMARE:
        r = per_episodio.get(eid)
        if r is None or vid in occupati or vid not in archivio:
            continue
        titoli = archivio[vid]['titoli']
        da_confermare.append({
            'trackId': eid, 'episode': r['episode'],
            'videoId': vid,
            'videoTitoli': titoli[:3],
            'motivo': motivo,
        })
    return len(nuovi), da_confermare


def main():
    percorso = BASE / "videos.json"
    originale = percorso.read_bytes()
    catalogo = json.loads(originale.decode("utf-8-sig"))
    episodi = leggi("episodi_apple.json").get("episodes")
    video = leggi("archivio_youtube.json").get("videos")
    controllo = leggi("controllo_video_meron.json")
    risultati = controllo.get("results")
    salvati = catalogo.get("videos") if isinstance(catalogo, dict) else None
    if not isinstance(episodi, list) or not episodi or not isinstance(video, list) or not video or not isinstance(salvati, dict) or not isinstance(risultati, list):
        raise ValueError("Archivi mancanti, vuoti o non validi: catalogo intatto")
    ids = [str(e.get("id", "")) if isinstance(e, dict) else "" for e in episodi]
    if any(not x.isdigit() for x in ids) or len(set(ids)) != len(ids):
        raise ValueError("ID Apple non validi o duplicati: catalogo intatto")
    archivio = {}
    for v in video:
        if not isinstance(v, dict):
            continue
        vid = video_id(v.get("url"))
        if vid and isinstance(v.get("title"), str) and v["title"].strip():
            archivio.setdefault(vid, {"titoli": []})["titoli"].append(v["title"])
    if not archivio:
        raise ValueError("Nessun video utilizzabile")
    lingua, varianti = titoli_italiani(archivio)
    for v in archivio.values():
        v["dettagli"] = [(t, dettagli(t)) for t in dict.fromkeys(v["titoli"])]
    stato_precedente = {str(r.get("trackId")): r.get("status") for r in risultati if isinstance(r, dict)}
    usati = {video_id(v.get("youtubeUrl")) for v in salvati.values() if isinstance(v, dict)} - {None}
    esiti = []
    for e, eid in zip(episodi, ids):
        if eid in salvati:
            continue
        titolo = e.get("titolo", "")
        if not isinstance(titolo, str) or not titolo.strip():
            raise ValueError("Titolo Apple mancante")
        a = dettagli(titolo)
        a["descr_indizi"] = dettagli(e.get("descrizione", ""))["indizi"]
        candidati = []
        for vid, v in archivio.items():
            valutazioni = [valuta(a, b, t, vid) for t, b in v["dettagli"]]
            # Seleziona la migliore variante dello STESSO video.
            c = max(valutazioni, key=lambda x: (not x["blocchi"], x["priorita"]))
            if c["comuni"]:
                candidati.append(c)
        utilizzabili = sorted([c for c in candidati if c["livello"] >= 2 and not c["blocchi"]],
                              key=lambda c: c["priorita"], reverse=True)
        stato, scelto = "DATI_INSUFFICIENTI", None
        if a["trailer"]:
            stato = "TRAILER"
        elif utilizzabili:
            c = utilizzabili[0]
            # Non sceglie arbitrariamente tra due video sullo stesso caso.
            if len(utilizzabili) > 1 and utilizzabili[1]["livello"] >= c["livello"]:
                stato = "PIU_VIDEO_COMPATIBILI"
            elif c["videoId"] in usati:
                stato = "VIDEO_GIA_ASSOCIATO"
            else:
                stato, scelto = "SELEZIONATO", c
        elif any(c["livello"] >= 2 and "PARTI_NON_ALLINEATE" in c["blocchi"] for c in candidati):
            stato = "PARTI_NON_ALLINEATE"
        elif any(c["livello"] >= 2 and "VERSIONI_DIVERSE" in c["blocchi"] for c in candidati):
            stato = "VERSIONI_DIVERSE"
        proposte = sorted(candidati, key=lambda c: c["priorita"], reverse=True)[:5]
        esiti.append({"trackId": eid, "episode": titolo, "stato_precedente": stato_precedente.get(eid),
                      "esito": stato, "selezionato": scelto, "proposte": proposte})
    assegnazioni = defaultdict(list)
    for r in esiti:
        if r["esito"] == "SELEZIONATO":
            assegnazioni[r["selezionato"]["videoId"]].append(r)
    for gruppo in assegnazioni.values():
        if len(gruppo) > 1:
            for r in gruppo:
                r["esito"] = "VIDEO_CONDIVISO_DA_DISTINGUERE"
                r["selezionato"] = None
    # Dopo il controllo standard, valuta le coppie PT.1 / PT.2
    # che puntano al medesimo video privo di numerazione.
    coppie_video_del_caso = collega_video_del_caso(esiti, usati, archivio)
    nuovi_v5 = recupera_ancore_v5(esiti, archivio, usati)
    nuovi_v6 = recupera_descrizioni_v6(esiti, archivio, usati, episodi)
    nuovi_v7, da_confermare_v7 = recupera_casi_v7(esiti, archivio, usati)

    aggiunte = {}
    data = datetime.now(timezone.utc).isoformat()
    for r in esiti:
        if r["esito"] not in ("SELEZIONATO", "VIDEO_DEL_CASO_CONDIVISO", "V5_CORRISPONDENZA", "V5_VIDEO_DEL_CASO_CONDIVISO", "V6_CORRISPONDENZA", "V7_CASO_DOCUMENTATO"):
            continue
        c = r["selezionato"]
        condiviso = r["esito"] in ("VIDEO_DEL_CASO_CONDIVISO", "V5_VIDEO_DEL_CASO_CONDIVISO")
        record = {"podcast": "Elisa True Crime", "episode": r["episode"],
            "youtubeUrl": c["url"], "verified": False, "automaticMatch": True,
            "matchMethod": "casi-documentati-v7" if r["esito"] == "V7_CASO_DOCUMENTATO" else ("titoli-descrizioni-v6" if r["esito"].startswith("V6_") else ("recupero-ancore-v5" if r["esito"].startswith("V5_") else ("recupero-tutti-v4" if condiviso else "recupero-tutti-v3"))),
            "matchedVideoTitle": c["title"],
            "matchRule": ("Stesso video ufficiale del caso per PT.1 e PT.2; "
                          "copertura intera da confermare" if condiviso
                          else c["regola"]), "addedAt": data}
        if condiviso:
            record.update({
                "sharedCaseVideo": True,
                "videoRelation": "video_del_caso",
                "videoLabel": "Guarda il video sul caso",
                "coversBothPartsConfirmed": r["sharedCoverageConfirmed"],
            })
        aggiunte[r["trackId"]] = record
    nuovi = len(aggiunte) if PUBBLICA else 0
    conteggi = Counter(r["esito"] for r in esiti)
    riepilogo = {"modalita": "PUBBLICAZIONE_AUTOMATICA" if PUBBLICA else "SOLO_SIMULAZIONE",
        "versione": "casi-documentati-v7", "episodi_apple": len(episodi),
        "nuovi_abbinamenti_v5": nuovi_v5, "nuovi_abbinamenti_v6": nuovi_v6,
        "nuovi_abbinamenti_v7": nuovi_v7, "casi_da_confermare_v7": len(da_confermare_v7),
        "coppie_pt1_pt2_con_video_del_caso": coppie_video_del_caso,
        "episodi_collegati_a_video_del_caso": 2 * coppie_video_del_caso,
        "video_archivio": len(archivio), "recupero_titoli_italiani": lingua,
        "varianti_aggiuntive": varianti, "episodi_gia_collegati": len(episodi) - len(esiti),
        "episodi_senza_collegamento_esaminati": len(esiti),
        "selezionati": len(aggiunte),
        "recuperati_da_DA_VERIFICARE": sum(r["esito"] == "SELEZIONATO" and r["stato_precedente"] == "DA_VERIFICARE" for r in esiti),
        "nuovi_collegamenti_aggiunti": nuovi,
        "totale_catalogo_prima": len(salvati), "totale_catalogo_dopo": len(salvati) + nuovi,
        "episodi_senza_collegamento_dopo": len(esiti) - nuovi, "motivi_attesa": dict(conteggi)}
    if PUBBLICA and aggiunte:
        if percorso.read_bytes() != originale:
            raise RuntimeError("Catalogo modificato durante il controllo: nessuna scrittura")
        salva("videos.json", {**catalogo, "videos": {**salvati, **aggiunte}})
    report = {"riepilogo": riepilogo, "verifiche": esiti,
              "da_confermare_v7": da_confermare_v7}
    salva("report_pubblicazione.json", report)
    # Il workflow carica gia questo file: include anche l'esito finale aggiornato.
    controllo["recupero_v3"] = report
    salva("controllo_video_meron.json", controllo)
    print("MERON - SIMULAZIONE CASI DOCUMENTATI V7" if not PUBBLICA else "MERON - RECUPERO CASI DOCUMENTATI V7")
    for nome, valore in riepilogo.items():
        print(f"{nome}: {valore}")
    for r in esiti:
        c = r["selezionato"]
        print(f"{r['esito']} | {r['episode']}" + (f" | {c['title']}" if c else ""))
    print("Un video del caso puo apparire in entrambe le parti, senza")
    print("confermare automaticamente che il contenuto copra entrambe.")
    print("Nessuna voce precedente eliminata o sovrascritta. verified resta false.")
    if da_confermare_v7:
        print("CASI DA CONFERMARE (NON PUBBLICATI):")
        for x in da_confermare_v7:
            print("DA_CONFERMARE | " + x['episode'] + " | " + ", ".join(x['videoTitoli'][:1]))
    if not PUBBLICA: print("SIMULAZIONE: videos.json non modificato; controllare il report V7.")
    print("Titoli compatibili non provano contenuti identici o riproducibilita.")
    print("Il passo successivo del workflow salva videos.json su GitHub.")


if __name__ == "__main__":
    main()
