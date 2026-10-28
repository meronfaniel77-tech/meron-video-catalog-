import json
import re
import unicodedata
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CONTROLLO = Path('controllo_video_meron.json')
CATALOGO = Path('videos.json')
REPORT = Path('simulazione_pubblicazione.json')

# Modalita sicura: questa versione NON scrive mai su videos.json.
PAROLE_GENERICHE = {
    'the', 'and', 'for', 'with', 'from', 'true', 'crime', 'elisa',
    'caso', 'case', 'storia', 'story', 'lato', 'oscuro', 'dark', 'side',
    'parte', 'part', 'episode', 'episodio', 'omicidio', 'murder',
    'scomparsa', 'missing', 'mistero', 'mystery', 'verita', 'truth',
    'della', 'delle', 'dello', 'degli', 'dalla', 'dalle', 'nella',
    'nelle', 'sulla', 'sulle', 'sono', 'questo', 'questa', 'come',
    'quando', 'perche', 'what', 'where', 'when', 'about', 'into',
    'dopo', 'prima', 'dentro', 'fuori', 'anni', 'giorni', 'tutti',
    'tutte', 'video', 'official', 'italiano', 'english', 'pt',
}


def leggi_json(percorso):
    with percorso.open('r', encoding='utf-8') as file:
        return json.load(file)


def normalizza(testo):
    testo = unicodedata.normalize('NFKD', str(testo or '').casefold())
    testo = ''.join(c for c in testo if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9 ]', ' ', testo)).strip()


def parole_specifiche(testo):
    return {
        parola for parola in normalizza(testo).split()
        if len(parola) >= 4 and parola not in PAROLE_GENERICHE
        and not parola.isdigit()
    }


def parte(testo):
    match = re.search(r'\b(?:pt|part|parte)\s*([1-9])\b', normalizza(testo))
    return int(match.group(1)) if match else None


def youtube_id(url):
    if not isinstance(url, str):
        return None
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.netloc not in ('www.youtube.com', 'youtube.com') or parsed.path != '/watch':
        return None
    ids = parse_qs(parsed.query).get('v', [])
    if len(ids) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{11}', ids[0]):
        return None
    return ids[0]


def verifica(episodio, video, url_esistenti, url_forti):
    motivi = []
    titolo = str(episodio.get('episode') or '')
    titolo_video = str(video.get('title') or '')
    url = video.get('url')
    identificativo = str(episodio.get('trackId') or '')
    parole_episodio = parole_specifiche(titolo)
    parole_video = parole_specifiche(titolo_video)
    comuni = parole_episodio & parole_video

    if not identificativo or not titolo or not titolo_video:
        motivi.append('Dati episodio o video incompleti')
    if not youtube_id(url):
        motivi.append('URL YouTube non valido')
    if url in url_esistenti:
        motivi.append('Video gia presente nel catalogo')
    if url_forti[url] > 1:
        motivi.append('Video proposto per piu episodi forti')

    parte_episodio, parte_video = parte(titolo), parte(titolo_video)
    if parte_episodio != parte_video and (parte_episodio is not None or parte_video is not None):
        motivi.append('Parte episodio non confermata')

    # Non basta una somiglianza generica o un punteggio alto:
    # almeno due parole specifiche devono coincidere nei titoli.
    if len(comuni) < 2:
        motivi.append('Meno di due parole specifiche in comune nei titoli')
    if len(parole_episodio) >= 2 and len(comuni) / len(parole_episodio) < 0.6:
        motivi.append('Copertura insufficiente del titolo Apple')

    candidati = episodio.get('candidates', [])
    if len(candidati) > 1:
        secondo = candidati[1]
        primo_score = video.get('score')
        secondo_score = secondo.get('score') if isinstance(secondo, dict) else None
        if isinstance(primo_score, (int, float)) and isinstance(secondo_score, (int, float)):
            if primo_score <= secondo_score * 1.5:
                motivi.append('Margine rispetto al secondo candidato insufficiente')

    return {
        'trackId': identificativo,
        'episode': titolo,
        'video': titolo_video,
        'url': url,
        'parole_specifiche_comuni': sorted(comuni),
        'esito': 'DA_RIVEDERE' if motivi else 'SUPERA_FILTRI',
        'motivi': motivi,
    }


def main():
    controllo = leggi_json(CONTROLLO)
    catalogo = leggi_json(CATALOGO)
    risultati = controllo.get('results')
    videos = catalogo.get('videos')
    if not isinstance(risultati, list) or not isinstance(videos, dict):
        raise ValueError('Formato JSON non valido')

    url_esistenti = {
        video.get('youtubeUrl') for video in videos.values()
        if isinstance(video, dict) and isinstance(video.get('youtubeUrl'), str)
    }
    forti = [e for e in risultati if isinstance(e, dict) and e.get('status') == 'CANDIDATO_FORTE']
    url_forti = Counter(
        e['candidates'][0].get('url')
        for e in forti
        if isinstance(e.get('candidates'), list) and e['candidates']
        and isinstance(e['candidates'][0], dict)
    )

    verifiche = []
    for episodio in forti:
        identificativo = str(episodio.get('trackId') or '')
        if identificativo in videos:
            continue
        opzioni = episodio.get('candidates', [])
        if not isinstance(opzioni, list) or not opzioni or not isinstance(opzioni[0], dict):
            verifiche.append({'trackId': identificativo, 'episode': episodio.get('episode'),
                              'esito': 'DA_RIVEDERE', 'motivi': ['Nessun candidato utilizzabile']})
            continue
        verifiche.append(verifica(episodio, opzioni[0], url_esistenti, url_forti))

    riepilogo = {
        'modalita': 'SOLO_SIMULAZIONE',
        'candidati_forti': len(forti),
        'gia_nel_catalogo': sum(str(e.get('trackId')) in videos for e in forti),
        'nuovi_da_esaminare': len(verifiche),
        'superano_filtri': sum(v['esito'] == 'SUPERA_FILTRI' for v in verifiche),
        'da_rivedere': sum(v['esito'] == 'DA_RIVEDERE' for v in verifiche),
        'totale_catalogo_invariato': len(videos),
    }
    with REPORT.open('w', encoding='utf-8') as file:
        json.dump({'riepilogo': riepilogo, 'verifiche': verifiche}, file, ensure_ascii=False, indent=2)
        file.write('\n')

    print('MERON - SIMULAZIONE CONTROLLO AUTOMATICO')
    for nome, valore in riepilogo.items():
        print(f'{nome}: {valore}')
    print('Creato:', REPORT)
    print('videos.json NON modificato')
    print('NOTA: SUPER A FILTRI non significa video verificato o autorizzato alla pubblicazione.')


if __name__ == '__main__':
    main()
