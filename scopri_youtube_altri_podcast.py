#!/usr/bin/env python3
"""MerON: confronta puntate Apple con i video di soli canali YouTube verificati.

MODALITA' SOLO RICOGNIZIONE: NON SCRIVE MAI videos.json e non pubblica video.
I match sono PROPOSTE e devono essere controllati prima della pubblicazione.
Nessuna ricerca YouTube libera e nessun download di file audio/video.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ID_YT = re.compile(r'UC[A-Za-z0-9_-]{22}\Z')
ID_VIDEO = re.compile(r'[A-Za-z0-9_-]{11}\Z')

# Escludi parole generiche, conduttori, brand e termini promozionali. Non sono prove
# che due episodi siano identici.
STOP = set('''
 a ad ai al alla alle allo anche ancora altre altri altro amici anno anni appunto
 abbiamo alla amaro amica amore and are as at bella bello ben buono con come cosa
 cui da dal dalla dei del della delle dello di do dopo due e ed edizione episode
 episodio episodi era essere fa fai fare fatto fedez finale fra full giacomo
 gazzoli gianluca gli grande grandi ha hanno host il in incontro intervista
 interviste io la le lo loro luca ma marra me mi mio mr nel nella nello ne noi
 non nostra nostro nuovo nuova nuove nuovi o of on one ore per podcast porcast
 poretcast passa piu po pod pulp puntata puntate quel questa questo rapone
 racconta racconti raccontare serie solo sono stefano su sul sulla supernova
 talk the time tinti tintoria tra un una uno video vita with youtube
 shorts short clip clips highlight highlights teaser trailer momenti estratto
 estratti meglio best oggi ieri speciale special dello stop loro quelli questa
 intervistato casadei gazzoli basement bsmt giacomo poretti daniele
 '''.split())

STOP |= {'parte', 'part', 'pt', 'stagione', 'season', 'episodio', 'ep', 's', 'live',
         'italiano', 'italia', 'online', 'risponde', 'risposta', 'scopri', 'svela',
         'rivelazione', 'storia', 'storie', 'realtà', 'reale', 'verita', 'vero',
         'vera', 'news', 'podcast', 'intervista', 'ufficiale'}

BLOCKED_VIDEO = re.compile(
    r'\b(?:shorts?|clips?|highlights?|trailer|teaser|promo|estratt[oi]|anticipazion[ei]|'
    r'best\s+of|momenti\s+migliori|backstage|dietro\s+le\s+quinte|reels?|'
    r'compilation|reaction)\b', re.I)
EP_NUMBER = re.compile(
    r'(?<!\w)#\s*(\d{1,4})\b|\b(?:ep(?:isodio)?|puntata|n\.|tintoria)\s*'
    r'[.#:\- ]*\s*(\d{1,4})\b', re.I)
SEASON = re.compile(r'\b(?:s\s*(\d{1,2})|stagione\s*(\d{1,2}))\b', re.I)
PART = re.compile(r'\b(?:pt|parte|part)\s*[.:-]?\s*(\d+)\b', re.I)
UPDATE = re.compile(r'\b(?:aggiornamento|update|updates|recap)\b', re.I)


def norm(text):
    text = unicodedata.normalize('NFKD', str(text or '').casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r'[^a-z0-9]+', ' ', text)
    return ' '.join(text.split())


def episode_meta(title):
    original = str(title or '')
    def num(rx):
        m = rx.search(original)
        if not m:
            return None
        return next((int(group) for group in m.groups() if group is not None), None)
    tokens = {w for w in norm(original).split()
              if len(w) >= 4 and w not in STOP and not w.isdigit()}
    return {'number': num(EP_NUMBER), 'season': num(SEASON),
            'part': num(PART), 'update': bool(UPDATE.search(original)),
            'tokens': tokens, 'clean': norm(original)}


def parse_date(value):
    if not isinstance(value, str):
        return None
    try:
        if re.fullmatch(r'\d{8}', value):
            return datetime.strptime(value, '%Y%m%d').date()
        return datetime.fromisoformat(value.replace('Z', '+00:00')).date()
    except ValueError:
        return None


def scoring(apple, video):
    """Return score/evidence, or None if data is insufficient/contradictory."""
    a, b = episode_meta(apple['title']), episode_meta(video['title'])
    if BLOCKED_VIDEO.search(video['title']) or BLOCKED_VIDEO.search(apple['title']):
        return None
    if a['update'] != b['update']:
        return None
    if (a['part'] is not None or b['part'] is not None) and a['part'] != b['part']:
        return None
    if a['number'] is not None and b['number'] is not None and a['number'] != b['number']:
        return None
    if a['season'] is not None and b['season'] is not None and a['season'] != b['season']:
        return None
    duration = video.get('duration')
    if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration < 600:
        return None

    common = a['tokens'] & b['tokens']
    if len(common) < 2 and not (a['number'] is not None and a['number'] == b['number'] and common):
        return None
    ratio = len(common) / max(1, min(len(a['tokens']), len(b['tokens'])))
    union = a['tokens'] | b['tokens']
    jaccard = len(common) / max(1, len(union))
    same_number = a['number'] is not None and a['number'] == b['number']
    same_season = (a['season'] == b['season'] and a['season'] is not None)
   
    # Per PoretCast i numeri ricominciano ogni stagione. Se soltanto uno dei
    # titoli dichiara la stagione, il numero da solo NON giustifica il match.
    uncertain_season = ((a['season'] is None) != (b['season'] is None))

    # Prima controlliamo se i titoli sono identici.
    if a['clean'] == b['clean'] and len(common) >= 2:
        score, rule = 112, 'Titolo identico'

    elif same_number and (same_season or not uncertain_season) and ratio >= 0.30:
        score, rule = 102 + min(len(common), 5) * 2, 'Numero di episodio e ospite/argomento coerenti'

    elif len(common) >= 2 and ratio >= 0.70 and jaccard >= 0.30:
        score, rule = 84 + min(len(common), 4) * 3 + int(jaccard * 10), 'Almeno due riferimenti distintivi condivisi'

    else:
        return None

    # Se il contenuto ha un numero esplicito in entrambe le fonti e la stagione
    # e' dichiarata da una sola, resta soltanto un candidato da verificare.
    if uncertain_season:
        score = min(score, 89)
        rule += '; stagione da verificare'
    if a['number'] is not None and b['number'] is None:
        score = min(score, 91)
        rule += '; numero assente su YouTube'
    elif b['number'] is not None and a['number'] is None:
        score = min(score, 91)
        rule += '; numero assente su Apple'

    day_a = parse_date(apple.get('releaseDate'))
    day_b = parse_date(video.get('uploadDate'))
    if day_a is not None and day_b is not None:
        days = abs((day_a - day_b).days)
        # Si tratta di una prima ricognizione: grandi differenze temporali
        # potrebbero indicare re-upload, compilation o versioni nuove.
        if days > 180:
            return None
        if days > 90:
            score = min(score, 89)
            rule += '; data diversa di oltre 90 giorni'

    known_duration = isinstance(duration, (int, float)) and duration >= 600
    return {
        'score': score, 'rule': rule, 'commonTokens': sorted(common),
        'episodeNumber': a['number'], 'season': a['season'],
        'youtubeDurationSeconds': duration if isinstance(duration, (int, float)) else None,
        'durationConfirmed': known_duration,
        'dateApple': apple.get('releaseDate'), 'dateYoutube': video.get('uploadDate'),
    }


def apple_lookup(collection_id, max_episodes):
    url = ('https://itunes.apple.com/lookup?id=' + collection_id
           + '&entity=podcastEpisode&country=IT&limit=' + str(max_episodes))
    request = urllib.request.Request(url, headers={
        'User-Agent': 'MerONYoutubePodcastDiscovery/1.0',
        'Accept': 'application/json'})
    with urllib.request.urlopen(request, timeout=27) as response:
        if urllib.parse.urlsplit(response.geturl()).hostname not in {'itunes.apple.com'}:
            raise ValueError('Redirect Apple non previsto')
        raw = response.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError('Risposta Apple troppo grande')
    data = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data.get('results'), list):
        raise ValueError('Risposta Apple non valida')
    out = []
    seen = set()
    for item in data['results']:
        if not isinstance(item, dict) or not (item.get('kind') == 'podcast-episode' or
                                             item.get('wrapperType') == 'podcastEpisode'):
            continue
        if str(item.get('collectionId', collection_id)) != collection_id:
            continue
        tid = item.get('trackId')
        title = item.get('trackName')
        if not isinstance(tid, int) or tid <= 0 or tid in seen or not isinstance(title, str) or not title.strip():
            continue
        seen.add(tid)
        out.append({'trackId': str(tid), 'title': title.strip(), 'releaseDate': item.get('releaseDate', '')})
    return out


# Alcuni podcast archiviano le puntate nella scheda "Dirette" (/streams).
# Scansioniamo solo le registrazioni pubbliche, mai gli Shorts.
MAX_YOUTUBE_STREAMS = 120


def youtube_channel(channel_id, max_videos, timeout=150):
    """Elenco video standard + dirette registrate dallo STESSO canale ufficiale.

    Il numero di upload ordinari e' quello configurato (massimo 250), mentre
    per i livestream si legge un numero limitato per contenere i tempi di GH.
    """
    if not ID_YT.fullmatch(channel_id):
        raise ValueError('ID canale non valido')

    videos = []
    seen = set()
    problems = []
    tabs = [('videos', max_videos), ('streams', min(MAX_YOUTUBE_STREAMS, max_videos))]
    for tab, cap in tabs:
        url = 'https://www.youtube.com/channel/' + channel_id + '/' + tab
        cmd = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--flat-playlist',
               '--skip-download', '--dump-single-json', '--no-warnings',
               '--playlist-end', str(cap), '--socket-timeout', '15',
               '--retries', '1', '--extractor-retries', '1', url]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    encoding='utf-8', errors='replace',
                                    timeout=max(45, timeout // 2))
            if result.returncode:
                raise RuntimeError('YouTube: ' + (result.stderr[-220:] or 'yt-dlp non riuscito'))
            data = json.loads(result.stdout)
            if not isinstance(data, dict) or not isinstance(data.get('entries'), list):
                raise ValueError('Elenco YouTube mancante')
            actual = data.get('channel_id')
            if actual and actual != channel_id:
                raise ValueError('Canale YouTube differente dal canale verificato')
            root_id = data.get('id')
            if (isinstance(root_id, str) and root_id.startswith(('UC', 'UU'))
                    and len(root_id) == 24
                    and root_id not in {channel_id, 'UU' + channel_id[2:]}):
                raise ValueError('ID del canale restituito inatteso')
            for item in data['entries']:
                if not isinstance(item, dict):
                    continue
                if item.get('channel_id') and item['channel_id'] != channel_id:
                    continue
                if item.get('live_status') in ('is_live', 'is_upcoming'):
                    continue
                vid, title = item.get('id'), item.get('title')
                if (not isinstance(vid, str) or not ID_VIDEO.fullmatch(vid)
                        or vid in seen or not isinstance(title, str) or not title.strip()):
                    continue
                seen.add(vid)
                videos.append({'videoId': vid, 'title': title.strip(),
                               'youtubeUrl': 'https://www.youtube.com/watch?v=' + vid,
                               'duration': item.get('duration'),
                               'uploadDate': item.get('upload_date') or item.get('release_date')})
        except (RuntimeError, ValueError, json.JSONDecodeError, subprocess.TimeoutExpired) as exc:
            problems.append(tab + ': ' + str(exc)[:170])
    if not videos:
        raise RuntimeError('Nessun video ufficiale leggibile. ' + '; '.join(problems))
    if problems:
        print('  AVVISO scansione parziale:', '; '.join(problems)[:260], flush=True)
    return videos


def match_episodes(apple_episodes, youtube_videos):
    """Risultati conservativi, con esclusione degli abbinamenti ambigui."""
    proposals = []
    for apple in apple_episodes:
        candidates = []
        for video in youtube_videos:
            rating = scoring(apple, video)
            if rating is not None:
                candidates.append({**rating, 'videoId': video['videoId'],
                                   'youtubeTitle': video['title'],
                                   'youtubeUrl': video['youtubeUrl']})
        candidates.sort(key=lambda v: (-v['score'], v['videoId']))
        if not candidates:
            continue
        best = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None
        reason = ''
        status = 'CANDIDATO_FORTE'
        if second and second['score'] >= best['score'] - 12:
            status, reason = 'DA_VERIFICARE', 'Piu video con valutazione simile'
        elif not best['durationConfirmed']:
            status, reason = 'DA_VERIFICARE', 'Durata del video non disponibile'
        elif best['score'] < 99:
            status, reason = 'DA_VERIFICARE', 'Somiglianza dei titoli non sufficiente per conferma automatica'
        proposals.append({'trackId': apple['trackId'], 'appleTitle': apple['title'],
                          'appleReleaseDate': apple.get('releaseDate'), 'status': status,
                          'reason': reason, 'best': best,
                          'alternatives': candidates[1:3]})
    # Una puntata Apple e un video YouTube devono essere in rapporto 1:1.
    claimed = defaultdict(list)
    for prop in proposals:
        if prop['status'] == 'CANDIDATO_FORTE':
            claimed[prop['best']['videoId']].append(prop)
    for group in claimed.values():
        if len(group) > 1:
            for prop in group:
                prop['status'] = 'DA_VERIFICARE'
                prop['reason'] = 'Lo stesso video risulta candidato per piu episodi Apple'
    return proposals


def config_checks(config):
    if not isinstance(config, dict) or not isinstance(config.get('podcasts'), list):
        raise ValueError('Configurazione non valida')
    podcasts = config['podcasts']
    if not podcasts or len(podcasts) > 50:
        raise ValueError('Numero di podcast fuori dai limiti')
    checked = set()
    for item in podcasts:
        if not isinstance(item, dict) or not str(item.get('appleCollectionId', '')).isdigit():
            raise ValueError('Apple collectionId mancante')
        if not ID_YT.fullmatch(str(item.get('youtubeChannelId', ''))):
            raise ValueError('YouTube channelId non valido')
        if item['appleCollectionId'] in checked:
            raise ValueError('Podcast Apple duplicato')
        checked.add(item['appleCollectionId'])
    max_apple = min(200, max(1, int(config.get('maxAppleEpisodesPerPodcast', 180))))
    max_video = min(250, max(1, int(config.get('maxYoutubeVideosPerChannel', 160))))
    timeout = min(240, max(30, int(config.get('channelTimeoutSeconds', 150))))
    return max_apple, max_video, timeout


def scan(config, fetch_apple=apple_lookup, fetch_youtube=youtube_channel):
    max_apple, max_video, timeout = config_checks(config)
    reports = []
    errors = []
    for idx, show in enumerate(config['podcasts'], 1):
        aid, yid = show['appleCollectionId'], show['youtubeChannelId']
        print(f'[{idx}/{len(config["podcasts"])}] {show["name"]}', flush=True)
        try:
            apple = fetch_apple(aid, max_apple)
            if not apple:
                raise ValueError('Apple non ha restituito episodi')
            print(f'  Episodi Apple: {len(apple)}', flush=True)
        except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            errors.append({'podcast': show['name'], 'phase': 'Apple', 'error': str(exc)[:320]})
            print(f'  AVVISO Apple: {str(exc)[:200]}', flush=True)
            continue
        try:
            videos = fetch_youtube(yid, max_video, timeout)
            print(f'  Video YouTube: {len(videos)}', flush=True)
        except (RuntimeError, ValueError, OSError, urllib.error.URLError) as exc:
            errors.append({'podcast': show['name'], 'phase': 'YouTube', 'error': str(exc)[:320]})
            print(f'  AVVISO YouTube: {str(exc)[:200]}', flush=True)
            continue
        proposals = match_episodes(apple, videos)
        count = Counter(p['status'] for p in proposals)
        print(f'  Candidati forti: {count["CANDIDATO_FORTE"]}; da verificare: {count["DA_VERIFICARE"]}', flush=True)
        reports.append({'name': show['name'], 'appleCollectionId': aid,
                        'youtubeChannelId': yid, 'officialUrl': show.get('officialUrl', ''),
                        'appleEpisodesRead': len(apple), 'youtubeVideosRead': len(videos),
                        'strongCandidates': count['CANDIDATO_FORTE'],
                        'toReview': count['DA_VERIFICARE'],
                        'noCandidate': len(apple) - len(proposals),
                        'proposals': proposals})
    return {'generatedAt': datetime.now(timezone.utc).isoformat(),
            'mode': 'SOLO_SIMULAZIONE', 'version': 'youtube-altri-podcast-v1',
            'notes': [
                'Non modifica videos.json o alcun file di Elisa True Crime.',
                'Canali YouTube consentiti solo dall elenco verificato in config.',
                'CANDIDATO_FORTE non implica verifica umana: non e ancora un collegamento pubblicato.',
                'L analisi e limitata agli ultimi episodi Apple e video YouTube esaminati.',
                'Problemi temporanei YouTube non vengono scambiati per assenza di video.'
            ],
            'showsConfigured': len(config['podcasts']), 'showsAnalyzed': len(reports),
            'totalStrongCandidates': sum(x['strongCandidates'] for x in reports),
            'totalToReview': sum(x['toReview'] for x in reports),
            'errors': errors, 'podcasts': reports}


def save_report(report, report_path, csv_path):
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    with csv_path.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['podcast', 'appleCollectionId', 'appleTrackId', 'episodioApple',
                         'esito', 'punteggio', 'videoYouTube', 'youtubeUrl', 'motivo'])
        for show in report['podcasts']:
            for prop in show['proposals']:
                writer.writerow([show['name'], show['appleCollectionId'], prop['trackId'],
                                 prop['appleTitle'], prop['status'], prop['best']['score'],
                                 prop['best']['youtubeTitle'], prop['best']['youtubeUrl'],
                                 prop['reason'] or prop['best']['rule']])


def main():
    parser = argparse.ArgumentParser(description='MerON - YouTube altri podcast (solo simulazione)')
    parser.add_argument('--config', default=str(BASE / 'config_youtube_altri_podcast.json'))
    parser.add_argument('--report', default=str(BASE / 'altri_podcast_youtube_report.json'))
    parser.add_argument('--csv', default=str(BASE / 'altri_podcast_youtube_candidati.csv'))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8-sig'))
    report = scan(config)
    save_report(report, Path(args.report), Path(args.csv))
    print('\nMERON - YOUTUBE ALTRI PODCAST (SOLO SIMULAZIONE)')
    print('podcast_configurati:', report['showsConfigured'])
    print('podcast_analizzati:', report['showsAnalyzed'])
    print('candidati_forti:', report['totalStrongCandidates'])
    print('da_verificare:', report['totalToReview'])
    print('errori:', len(report['errors']))
    for show in report['podcasts']:
        print(f'- {show["name"]}: {show["strongCandidates"]} forti, {show["toReview"]} da verificare')
    for error in report['errors']:
        print(f'AVVISO [{error["phase"]}]: {error["podcast"]}: {error["error"]}')
    print('videos.json: INALTERATO; nessun collegamento pubblicato.')
    print('Report: altri_podcast_youtube_report.json, altri_podcast_youtube_candidati.csv')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
