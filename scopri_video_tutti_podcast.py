#!/usr/bin/env python3
"""MerON: scansione estendibile dei podcast Apple e dei loro video YouTube.

NON MODIFICA MAI videos.json. Può essere eseguito ogni giorno, a lotti,
memorizzando in stato_video_tutti_podcast.json i podcast già controllati.

Riusa esclusivamente il matcher e i filtri di sicurezza già installati in MerON:
- scopri_youtube_altri_podcast.py
- pubblica_video_altri_podcast.py

Un canale YouTube nuovo è accettato solo se indicato dal feed Apple del
podcast o dal sito che quel feed dichiara ufficiale. Non si usa ytsearch.
"""
from __future__ import annotations

import csv
import html
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
import unicodedata
from pathlib import Path

import scopri_youtube_altri_podcast as yt
import pubblica_video_altri_podcast as publish

BASE = Path(__file__).resolve().parent
STATE_FILE = BASE / 'stato_video_tutti_podcast.json'
CONFIG_FILE = BASE / 'config_video_tutti_podcast.json'
SUMMARY_FILE = BASE / 'rapporto_video_tutti_podcast.json'
DETAIL_FILE = BASE / 'anteprima_video_tutti_podcast.json'
CSV_FILE = BASE / 'anteprima_video_tutti_podcast.csv'
DYNAMIC_CONFIG_FILE = BASE / 'config_batch_video_tutti_podcast.json'
YOUTUBE_REPORT_FILE = BASE / 'rapporto_youtube_batch_tutti_podcast.json'

ID_APPLE = re.compile(r'^[0-9]{5,20}$')
ID_CHANNEL = re.compile(r'^UC[A-Za-z0-9_-]{22}$')
CHANNEL_URL = re.compile(
    r'https://(?:www\.|m\.)?youtube\.com/'
    r'(?:channel/UC[A-Za-z0-9_-]{22}|@[A-Za-z0-9_.-]{3,60}|c/[A-Za-z0-9_.-]{3,60}|user/[A-Za-z0-9_.-]{3,60})',
    re.IGNORECASE,
)
TAG_LINK = re.compile(r'<(?:[A-Za-z_][\w.-]*:)?link\s*>(.*?)</(?:[A-Za-z_][\w.-]*:)?link\s*>', re.I | re.S)
CHANNEL_START = re.compile(r'<(?:[\w.-]+:)?channel(?:\s[^>]*)?>', re.I)
ITEM_START = re.compile(r'<(?:[\w.-]+:)?item(?:\s[^>]*)?>', re.I)
ITEM_END = re.compile(r'</(?:[\w.-]+:)?item\s*>', re.I)
MAX_READ_SITE = 350 * 1024
MAX_READ_RSS_HEAD = 280 * 1024
MAX_READ_APPLE = 3 * 1024 * 1024
APPLE_MIN_INTERVAL = 3.1  # Documentazione Apple: circa 20 richieste al minuto
LAST_APPLE_REQUEST = 0.0
DISCOVERY_REVISION = 4
MAX_INTERNAL_PAGES = 3  # non seguire un intero sito, solo pagine rilevanti
MAX_RUN_SECONDS = 2700  # interrompe in sicurezza prima del timeout di GitHub Actions

# Canali verificati da fonti pubbliche riconducibili al podcast. Sono pochi
# casi documentati, NON una ricerca euristica che indovina i proprietari.
# Anche qui il programma pubblica soltanto tramite l'altro workflow.
CANALI_DOCUMENTATI_V4 = {
    '1616476688': {
        'name': 'Indagini',
        'youtubeUrl': 'https://www.youtube.com/channel/UCm6hxoiPOykrgjVG8y6wY3g',
        'proof': 'Canale Indagini: descrizione ufficiale Il Post / Stefano Nazzi',
        'sourceUrl': 'https://www.youtube.com/channel/UCm6hxoiPOykrgjVG8y6wY3g',
    },
    '1775666184': {
        'name': 'SUPERNOVA',
        'youtubeUrl': 'https://www.youtube.com/@StaseraAleCattelan',
        'proof': 'Link al canale riportato nella descrizione delle puntate SUPERNOVA',
        'sourceUrl': 'https://choramedia.com/podcast/supernova/',
    },
    '1694669718': {
        'name': 'De Core - Podcast',
        'youtubeUrl': 'https://www.youtube.com/@decore_podcast',
        'proof': 'Linktree del programma con corrispondenze Apple e YouTube per numero e ospite',
        'sourceUrl': 'https://linktr.ee/decore_podcast',
    },
}


def now():
    return datetime.now(timezone.utc)


def iso_now():
    return now().isoformat()


def parse_when(s):
    try:
        result = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
        return result.astimezone(timezone.utc) if result.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def load_obj(path, default):
    if not path.exists():
        return default
    obj = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(obj, dict):
        raise ValueError(f'{path.name}: atteso oggetto JSON')
    return obj


def atomic_json(path, obj):
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix='meron-universale-', suffix='.tmp')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def validate_config(conf):
    if not isinstance(conf.get('country'), str) or not re.fullmatch('[A-Za-z]{2}', conf['country']):
        raise ValueError('country deve avere due lettere')
    for key, low, high in (
        ('chartLimit', 1, 200), ('maxShowsPerRun', 1, 50),
        ('maxYoutubeChannelsPerRun', 1, 20), ('maxAppleEpisodesPerPodcast', 1, 200),
        ('maxYoutubeVideosPerChannel', 1, 250), ('channelTimeoutSeconds', 30, 240),
        ('daysUntilRescan', 1, 60), ('daysUntilRetryWithoutChannel', 1, 120),
    ):
        v = conf.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or not low <= v <= high:
            raise ValueError(f'{key}: intero richiesto tra {low} e {high}')
    if not isinstance(conf.get('genres'), list) or len(conf['genres']) > 35:
        raise ValueError('genres non valido')
    for genre in conf['genres']:
        if genre != 'all' and not re.fullmatch(r'\d{3,6}', str(genre)):
            raise ValueError(f'genere non valido: {genre}')
    if not isinstance(conf.get('additionalPodcastIds'), list):
        raise ValueError('additionalPodcastIds non valido')
    if not isinstance(conf.get('excludedPodcastIds'), list):
        raise ValueError('excludedPodcastIds non valido')
    for cid in conf['additionalPodcastIds'] + conf['excludedPodcastIds']:
        if not ID_APPLE.fullmatch(str(cid)):
            raise ValueError('ID Apple aggiuntivo/escluso non valido')
    if conf.get('mode') != 'SOLO_SIMULAZIONE':
        raise ValueError('Pubblicazione disattivata: mode deve essere SOLO_SIMULAZIONE')


def public_https(url):
    """Difesa per fetch di URL indicati da terze parti (RSS/sito)."""
    if not isinstance(url, str) or len(url) > 2048:
        return False
    try:
        p = urllib.parse.urlsplit(url)
        host = (p.hostname or '').lower().rstrip('.')
        if (p.scheme != 'https' or not host or p.username or p.password or
                p.port not in (None, 443) or host == 'localhost' or
                host.endswith(('.local', '.internal', '.localhost'))):
            return False
        try:
            ip = ipaddress.ip_address(host)
            if not ip.is_global:
                return False
        except ValueError:
            pass
        addrs = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        return bool(addrs) and all(ipaddress.ip_address(a[4][0]).is_global for a in addrs)
    except (ValueError, TypeError, OverflowError, OSError):
        return False


class PublicRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not public_https(newurl):
            raise ValueError('Redirect non pubblico/non HTTPS')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


FETCHER = urllib.request.build_opener(PublicRedirect())


def fetch_limited(url, cap, timeout=15):
    if not public_https(url):
        raise ValueError('URL non HTTPS o host non pubblico')
    req = urllib.request.Request(url, headers={
        'User-Agent': 'MerONUniversalVideoDiscovery/1.0',
        'Accept': 'application/json, text/html, application/rss+xml, application/xml, text/xml, */*',
    })
    with FETCHER.open(req, timeout=timeout) as response:
        if not public_https(response.geturl()):
            raise ValueError('URL finale non pubblico')
        return response.read(cap)


def apple_get(url):
    global LAST_APPLE_REQUEST
    target = urllib.parse.urlsplit(url)
    if target.scheme != 'https' or target.hostname != 'itunes.apple.com':
        raise ValueError('Origine API Apple inattesa')
    wait = APPLE_MIN_INTERVAL - (time.monotonic() - LAST_APPLE_REQUEST)
    if wait > 0:
        time.sleep(wait)
    LAST_APPLE_REQUEST = time.monotonic()
    raw = fetch_limited(url, MAX_READ_APPLE, timeout=20)
    if len(raw) >= MAX_READ_APPLE:
        raise ValueError('Risposta Apple oltre il limite')
    return json.loads(raw.decode('utf-8-sig'))


def read_charts(conf):
    country = conf['country'].lower()
    limit = conf['chartLimit']
    genres = ['all'] + [str(g) for g in conf['genres'] if str(g) != 'all']
    all_shows, problems = {}, []
    for genre in dict.fromkeys(genres):
        suffix = '' if genre == 'all' else f'/genre={genre}'
        url = f'https://itunes.apple.com/{country}/rss/toppodcasts/limit={limit}{suffix}/json'
        try:
            data = apple_get(url)
            entries = data.get('feed', {}).get('entry', [])
            if isinstance(entries, dict):
                entries = [entries]
            if not isinstance(entries, list) or not entries:
                raise ValueError('Classifica vuota o formato inatteso')
            count = 0
            for item in entries:
                if not isinstance(item, dict):
                    continue
                cid = str(item.get('id', {}).get('attributes', {}).get('im:id', ''))
                if ID_APPLE.fullmatch(cid):
                    all_shows.setdefault(cid, {
                        'name': item.get('im:name', {}).get('label', '') or cid,
                        'source': 'classifica_apple_' + genre,
                    })
                    count += 1
            print(f'  Classifica Apple {genre}: {count} risultati', flush=True)
        except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            problems.append({'genre': genre, 'error': str(exc)[:220]})
            print(f'  AVVISO classifica {genre}: {str(exc)[:140]}', flush=True)
    return all_shows, problems


def decode_markup(raw):
    return html.unescape(raw.decode('utf-8', errors='replace').replace('\\/', '/'))


def extract_channels(text):
    links = []
    for match in CHANNEL_URL.finditer(text):
        url = match.group(0)
        path = urllib.parse.urlsplit(url).path
        # Elimina suffissi non necessari e normalizza URL canale.
        if path.startswith('/channel/'):
            cid = path.split('/')[2]
            if ID_CHANNEL.fullmatch(cid):
                url = f'https://www.youtube.com/channel/{cid}'
        else:
            url = 'https://www.youtube.com' + path
        if url not in links:
            links.append(url)
    return links


def rss_channel_meta(raw):
    """Il feed può essere enorme: ci basta l'intestazione prima del primo item."""
    src = decode_markup(raw)
    start = CHANNEL_START.search(src)
    if not start:
        return '', []
    body = src[start.end():]
    item = ITEM_START.search(body)
    if item:
        body = body[:item.start()]
    links = TAG_LINK.findall(body)
    website = html.unescape(re.sub(r'<[^>]+>', '', links[0]).strip()) if links else ''
    return website, extract_channels(body)


def repeated_rss_channel(raw, min_episodes=3):
    """Canale citato in almeno 3 episodi del FEED del publisher.

    Non basta un link in un singolo episodio, che potrebbe essere
    di un ospite o di un canale di terzi. Se due canali ricorrono
    con frequenze simili, il risultato resta ambiguo.
    """
    src = decode_markup(raw)
    first = ITEM_START.search(src)
    if not first:
        return None
    counts = Counter()
    end_from = first.start()
    scanned = 0
    while scanned < 30:
        start = ITEM_START.search(src, end_from)
        if not start:
            break
        end = ITEM_END.search(src, start.end())
        if not end:
            break
        body = src[start.end():end.start()]
        for channel_url in set(extract_channels(body)):
            counts[channel_url] += 1
        scanned += 1
        end_from = end.end()
    if not counts:
        return None
    ranked = counts.most_common(2)
    best, n = ranked[0]
    if n < min_episodes:
        return None
    if len(ranked) > 1 and ranked[1][1] >= n:
        return None
    return best


def apple_show(cid, country):
    data = apple_get(f'https://itunes.apple.com/lookup?id={cid}&country={country.upper()}')
    for item in data.get('results', []):
        if str(item.get('collectionId')) == cid and item.get('collectionName'):
            return {
                'name': item.get('collectionName'),
                'feedUrl': item.get('feedUrl', ''),
                'artist': item.get('artistName', ''),
            }
    raise ValueError('Podcast non trovato tramite lookup Apple')



class InternalSiteLinks(HTMLParser):
    """Estrae solo i link HTML del sito dichiarato nel feed Apple."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            href = dict(attrs).get('href')
            self.anchor = {'href': href, 'label': []} if isinstance(href, str) else None

    def handle_data(self, data):
        if self.anchor is not None:
            self.anchor['label'].append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'a' and self.anchor is not None:
            self.links.append((self.anchor['href'], ' '.join(self.anchor['label'])))
            self.anchor = None


def simplify(s):
    t = unicodedata.normalize('NFKD', str(s).casefold())
    t = ''.join(ch for ch in t if not unicodedata.combining(ch))
    return ' '.join(re.findall(r'[a-z0-9]+', t))


def site_internal_pages(html_text, site_url, show_name, *, max_items=MAX_INTERNAL_PAGES):
    """Seleziona poche pagine interne che parlano del podcast.

    Evita links a domini esterni, http, file, redirect e media. Il controllo DNS
    e dei redirect resta obbligatorio durante fetch_limited().
    """
    parser = InternalSiteLinks()
    try:
        parser.feed(html_text)
    except (ValueError, TypeError):
        return []
    root = urllib.parse.urlsplit(site_url)
    host = (root.hostname or '').lower().removeprefix('www.')
    show_words = {w for w in simplify(show_name).split()
                  if len(w) >= 4 and w not in {'podcast', 'della', 'dello', 'degli',
                                              'delle', 'with', 'italiano', 'italiana',
                                              'show', 'stories', 'story', 'radio'}}
    generic = {'podcast', 'podcasts', 'video', 'youtube', 'canale', 'ascolta',
               'trasmissione', 'programma', 'programmi', 'show', 'chi-siamo',
               'about', 'contatti', 'episodes', 'episodi', 'puntate'}
    relevant = []
    seen = set()
    for href, label in parser.links:
        if not isinstance(href, str) or not href.strip():
            continue
        u = urllib.parse.urljoin(site_url, html.unescape(href.strip()))
        try:
            p = urllib.parse.urlsplit(u)
            h = (p.hostname or '').lower().removeprefix('www.')
            port = p.port
        except ValueError:
            continue
        if p.scheme != 'https' or h != host or port not in (None, 443):
            continue
        path = p.path.rstrip('/') or '/'
        if path == (root.path.rstrip('/') or '/'):
            continue
        if (re.search(r'\.(?:jpg|jpeg|webp|png|gif|pdf|mp3|mp4|m4a|zip|xml|rss|json)$', path, re.I)
                or len(path) > 220 or path in seen):
            continue
        seen.add(path)
        cues = set(simplify(path + ' ' + label).split())
        matches = len(show_words & cues)
        score = (7 if show_words and matches >= min(2, len(show_words)) else
                 4 if matches else 1 if generic & cues else 0)
        if score:
            # Elimina query e fragment: non sono parte della prova di origine.
            relevant.append((score, path, f'https://{p.netloc}{path}'))
    relevant.sort(key=lambda item: (-item[0], len(item[1]), item[1]))
    return [(score, url) for score, _, url in relevant[:max_items]]


def choose_official_channel(show, *, get=fetch_limited):
    """Canale ammesso SOLO se collegato direttamente dal feed/sito ufficiale.

    V3: se l'homepage non lo espone, controlla poche pagine interne realmente
    pertinenti al podcast. Mai usare ytsearch come prova di ufficialita'.
    """
    feed_url = show.get('feedUrl') or ''
    if not public_https(feed_url):
        return None, 'FEED_NON_HTTPS_O_NON_PUBBLICO'
    try:
        rss_head = get(feed_url, MAX_READ_RSS_HEAD, 17)
        site, direct = rss_channel_meta(rss_head)
    except (ValueError, OSError, urllib.error.URLError) as exc:
        return None, 'FEED_INACCESSIBILE: ' + str(exc)[:110]
    if len(direct) == 1:
        return direct[0], 'LINK_NEL_FEED_APPLE'
    if len(direct) > 1:
        return None, 'PIU_CANALI_YOUTUBE_NEL_FEED'
    # Nei feed molti editori indicano il proprio YouTube nella descrizione
    # di ogni episodio, ma NON nell'intestazione <channel>.
    repeating = repeated_rss_channel(rss_head)
    if repeating:
        return repeating, 'STESSO_LINK_YOUTUBE_IN_TRE_EPISODI_DEL_FEED'
    if not site or not public_https(site):
        return None, 'CANALE_YOUTUBE_NON_VERIFICABILE'
    # URL <channel><link> del feed: la sorgente e' scelta dal publisher.
    direct_site = extract_channels(site)
    if len(direct_site) == 1:
        return direct_site[0], 'LINK_PRINCIPALE_DEL_FEED'
    if len(direct_site) > 1:
        return None, 'PIU_CANALI_YOUTUBE_NEL_LINK_PRINCIPALE'
    try:
        page_text = decode_markup(get(site, MAX_READ_SITE, 13))
    except (ValueError, OSError, urllib.error.URLError) as exc:
        return None, 'SITO_INACCESSIBILE: ' + str(exc)[:110]
    found = extract_channels(page_text)
    if len(found) == 1:
        return found[0], 'LINK_SUL_SITO_INDICATO_DAL_FEED'

    # I siti multi-podcast (editori e network) spesso espongono il canale solo
    # nella pagina dedicata al singolo show, non sulla homepage.
    for score, url in site_internal_pages(page_text, site, show.get('name', '')):
        if not public_https(url):
            continue
        try:
            internal_text = decode_markup(get(url, MAX_READ_SITE, 7))
        except (ValueError, OSError, urllib.error.URLError):
            continue
        internal = extract_channels(internal_text)
        if len(internal) == 1 and (len(found) == 0 or score >= 4):
            # Se la homepage contiene vari canali, accettiamo solo una pagina
            # specifica per il podcast e un link univoco al canale.
            return internal[0], 'LINK_NELLA_PAGINA_UFFICIALE_DEL_PODCAST'
    if len(found) > 1:
        return None, 'PIU_CANALI_YOUTUBE_SUL_SITO'
    return None, 'CANALE_YOUTUBE_NON_VERIFICABILE'

def resolve_channel(url, timeout=55):
    match = re.fullmatch('https://www.youtube.com/channel/(UC[A-Za-z0-9_-]{22})', url)
    if match:
        return match.group(1)
    cmd = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--flat-playlist',
           '--skip-download', '--dump-single-json', '--no-warnings',
           '--playlist-end', '1', '--socket-timeout', '10', '--retries', '1',
           '--extractor-retries', '1', url + '/videos']
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           encoding='utf-8', errors='replace', timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError('Risoluzione canale YouTube scaduta') from exc
    if p.returncode:
        raise RuntimeError('YouTube: ' + (p.stderr[-180:] or 'impossibile risolvere handle'))
    doc = json.loads(p.stdout)
    cid = doc.get('channel_id') or doc.get('id')
    if not isinstance(cid, str) or not ID_CHANNEL.fullmatch(cid):
        raise ValueError('Identità del canale YouTube non confermata')
    return cid


def recency_days(last_attempt, days):
    dt = parse_when(last_attempt)
    return dt is not None and now() - dt < timedelta(days=days)


def status_due(saved, conf):
    if not saved:
        return True
    flag = saved.get('status')
    # Dopo un miglioramento del rilevamento canali, riprova subito gli show
    # rimasti senza canale con una vecchia versione del programma.
    if flag == 'SENZA_CANALE_VERIFICABILE' and saved.get('discoveryRevision', 0) < DISCOVERY_REVISION:
        return True
    if flag in {'SCANSIONATO', 'GIA_COPERTO_DAL_CATALOGO'}:
        days = conf['daysUntilRescan']
    elif flag in {'DA_SCANSIONARE', 'IN_ATTESA_DI_SCANSIONE'}:
        return True
    elif flag == 'ERRORE':
        days = 2
    else:
        days = conf['daysUntilRetryWithoutChannel']
    return not recency_days(saved.get('lastAttempt'), days)


def existing_show_ids(catalog):
    found = set()
    for info in catalog.get('videos', {}).values():
        if isinstance(info, dict):
            cid = str(info.get('appleCollectionId', ''))
            if ID_APPLE.fullmatch(cid):
                found.add(cid)
    return found


def imported_meron_catalog():
    """Facoltativo: IDs esportati dal catalogo MerON, se disponibili.
    Non presume che i soli podcast delle classifiche siano tutti quelli
    accessibili dalla ricerca in MerON.
    """
    source = BASE / 'catalogo_podcast_meron.json'
    if not source.exists():
        return {}
    data = load_obj(source, {})
    entries = data.get('podcasts', [])
    if not isinstance(entries, list) or len(entries) > 100000:
        raise ValueError('catalogo_podcast_meron.json non valido')
    found = {}
    for item in entries:
        if isinstance(item, dict):
            cid = str(item.get('collectionId', item.get('appleCollectionId', '')))
            name = str(item.get('name', item.get('collectionName', cid)))
        else:
            cid = str(item)
            name = cid
        if ID_APPLE.fullmatch(cid):
            found[cid] = {'name': name[:180], 'source': 'CATALOGO_MERON'}
    return found


def make_batch_config(conf, successes):
    return {'maxAppleEpisodesPerPodcast': conf['maxAppleEpisodesPerPodcast'],
            'maxYoutubeVideosPerChannel': conf['maxYoutubeVideosPerChannel'],
            'channelTimeoutSeconds': conf['channelTimeoutSeconds'],
            'podcasts': successes}


def empty_yt_report():
    return {'generatedAt': iso_now(), 'mode': 'SOLO_SIMULAZIONE',
            'version': 'youtube-altri-podcast-v1', 'showsConfigured': 0,
            'showsAnalyzed': 0, 'totalStrongCandidates': 0, 'totalToReview': 0,
            'errors': [], 'podcasts': []}


def preview_batch(report, catalog, batch_conf):
    # La V1 precedente è in modalità pubblicazione sul repository dell'utente.
    # Qui *mai* chiamare main() o aggiornare videos.json: riusare soltanto il filtro.
    publish.PUBBLICA = False
    if not batch_conf['podcasts']:
        return {'summary': {'mode': 'SOLO_SIMULAZIONE',
                            'nuoviCollegamentiSelezionati': 0,
                            'sospesiPerSicurezza': 0,
                            'giaPresentiIdentici': 0,
                            'catalogoPrima': len(catalog['videos']),
                            'catalogoDopo': len(catalog['videos'])},
                'selected': [], 'held': [], 'existing': []}
    return publish.safe_candidates(report, catalog, batch_conf)


def main():
    start_monotonic = time.monotonic()
    conf = load_obj(CONFIG_FILE, None)
    if not conf:
        raise ValueError('config_video_tutti_podcast.json assente')
    validate_config(conf)
    original_catalog = (BASE / 'videos.json').read_bytes()
    catalog = json.loads(original_catalog.decode('utf-8-sig'))
    if not isinstance(catalog, dict) or not isinstance(catalog.get('videos'), dict):
        raise ValueError('videos.json non valido; nessuna azione')
    old_state = load_obj(STATE_FILE, {'version': 1, 'shows': {}, 'chartShows': {}, 'chartRefreshed': ''})
    state = json.loads(json.dumps(old_state))
    if state.get('version') != 1 or not isinstance(state.get('shows'), dict) or not isinstance(state.get('chartShows'), dict):
        raise ValueError('Stato della scansione in formato inatteso')

    chart_errors = []
    if not recency_days(state.get('chartRefreshed'), 7):
        print('MERON - AGGIORNAMENTO CATALOGO APPLE PER CATEGORIE', flush=True)
        charts, chart_errors = read_charts(conf)
        state['chartShows'].update(charts)
        if charts:
            state['chartRefreshed'] = iso_now()
        print('Podcast unici scoperti nei grafici Apple:', len(state['chartShows']), flush=True)

    known = load_obj(BASE / 'config_youtube_altri_podcast.json', {'podcasts': []})
    known_map = {}
    for entry in known.get('podcasts', []):
        cid = str(entry.get('appleCollectionId', ''))
        if ID_APPLE.fullmatch(cid) and ID_CHANNEL.fullmatch(str(entry.get('youtubeChannelId', ''))):
            known_map[cid] = entry
    excludes = {str(x) for x in conf['excludedPodcastIds']}
    catalog_covered = existing_show_ids(catalog)
    sources = {}
    # Precedenza ai podcast aggiuntivi, poi alle classifiche; i cinque già coperti
    # vengono ripresi per le nuove puntate solo alla scadenza del controllo.
    for cid, item in imported_meron_catalog().items():
        sources.setdefault(cid, item)
    for cid in conf['additionalPodcastIds']:
        sources.setdefault(str(cid), {'name': str(cid), 'source': 'ID_AGGIUNTIVO'})
    for cid, item in state['chartShows'].items():
        if ID_APPLE.fullmatch(str(cid)) and isinstance(item, dict):
            sources.setdefault(cid, item)
    for cid, item in known_map.items():
        sources.setdefault(cid, {'name': item.get('name', cid), 'source': 'CANALE_GIA_VERIFICATO'})
    for cid, item in CANALI_DOCUMENTATI_V4.items():
        sources.setdefault(cid, {'name': item['name'], 'source': 'CANALE_DOCUMENTATO_V4'})

    # Lotti progressivi: prima i canali gia' scoperti ma ancora da scansionare,
    # poi i podcast MAI controllati, infine gli aggiornamenti periodici.
    # Senza questo ordine, i ricontrolli ogni 14 giorni potrebbero impedire
    # di raggiungere le categorie piu' lontane della classifica.
    def canale_nuovo_gia_documentato(cid, previous):
        return (not previous or not previous.get('youtubeChannelId')) and (
            cid in known_map or cid in CANALI_DOCUMENTATI_V4)

    def order(index_item):
        index, (cid, _) = index_item
        previous = state['shows'].get(cid)
        if previous and previous.get('status') == 'DA_SCANSIONARE':
            return (0, str(previous.get('lastAttempt', '')), index)
        if canale_nuovo_gia_documentato(cid, previous):
            return (1, '', index)
        # Non riprovare immediatamente 40 fallimenti: esploriamo prima i nuovi.
        if not previous:
            return (2, '', index)
        if (previous and previous.get('status') == 'SENZA_CANALE_VERIFICABILE'
                and previous.get('discoveryRevision', 0) < DISCOVERY_REVISION):
            return (3, str(previous.get('lastAttempt', '')), index)
        return (4, str(previous.get('lastAttempt', '')), index)

    todo = [item for _, item in sorted(enumerate(sources.items()), key=order)]
    logs = []
    examined = 0
    youtube_scanned = 0
    youtube_success = []
    youtube_reports = []
    riesaminati = 0
    canali_documentati_scansionati = 0
    stopped_for_time = False
    for cid, listing in todo:
        if time.monotonic() - start_monotonic > MAX_RUN_SECONDS:
            stopped_for_time = True
            print("Tempo massimo del lotto raggiunto: proseguo al prossimo avvio.", flush=True)
            break
        if cid in excludes:
            continue
        previous = state['shows'].get(cid)
        if not previous and cid in catalog_covered:
            state['shows'][cid] = {
                'name': listing.get('name', cid), 'status': 'GIA_COPERTO_DAL_CATALOGO',
                'lastAttempt': iso_now(), 'youtubeChannelId': known_map.get(cid, {}).get('youtubeChannelId', ''),
                'source': 'videos.json',
            }
            continue
        if not status_due(previous, conf) and not canale_nuovo_gia_documentato(cid, previous):
            continue
        if examined >= conf['maxShowsPerRun']:
            break
        examined += 1
        label = (previous or {}).get('name') or listing.get('name') or cid
        print(f'[{examined}/{conf["maxShowsPerRun"]}] {label} - Apple {cid}', flush=True)
        if (previous and previous.get('status') == 'SENZA_CANALE_VERIFICABILE'
                and previous.get('discoveryRevision', 0) < DISCOVERY_REVISION):
            riesaminati += 1
        record = dict(previous or {})
        record.update({'name': label, 'lastAttempt': iso_now(),
                       'discoveryRevision': DISCOVERY_REVISION})
        status = 'ERRORE'
        try:
            cid_channel = record.get('youtubeChannelId')
            if cid in known_map:
                cid_channel = known_map[cid]['youtubeChannelId']
                record.update({'youtubeChannelId': cid_channel, 'channelProof': 'CONFIGURAZIONE_PREESISTENTE'})
            if not cid_channel and cid in CANALI_DOCUMENTATI_V4:
                doc = CANALI_DOCUMENTATI_V4[cid]
                cid_channel = resolve_channel(doc['youtubeUrl'])
                record.update({'youtubeChannelId': cid_channel,
                               'channelProof': 'CANALE_DOCUMENTATO_V4: ' + doc['proof'],
                               'youtubeSourceUrl': doc['sourceUrl']})
            if not cid_channel:
                apple_show_data = apple_show(cid, conf['country'])
                record['name'] = apple_show_data['name']
                link, proof = choose_official_channel(apple_show_data)
                record['channelProof'] = proof
                if link:
                    cid_channel = resolve_channel(link)
                    record['youtubeChannelId'] = cid_channel
                    record['youtubeSourceUrl'] = link
            if not cid_channel:
                status = 'SENZA_CANALE_VERIFICABILE'
                print(f'  Nessun canale ufficiale ricavabile: {record.get("channelProof")}', flush=True)
            elif not ID_CHANNEL.fullmatch(str(cid_channel)):
                raise ValueError('ID canale non valido')
            elif youtube_scanned >= conf['maxYoutubeChannelsPerRun']:
                status = 'DA_SCANSIONARE'
                print('  Canale trovato; la scansione YouTube proseguirà nel prossimo lotto', flush=True)
            else:
                youtube_scanned += 1
                if cid in CANALI_DOCUMENTATI_V4:
                    canali_documentati_scansionati += 1
                # Scansione Apple + YouTube tramite l'algoritmo già verificato.
                batch_entry = {'appleCollectionId': cid, 'name': record['name'],
                               'youtubeChannelId': cid_channel,
                               'officialUrl': record.get('youtubeSourceUrl') or known_map.get(cid, {}).get('officialUrl', ''),
                               'evidence': record.get('channelProof', '')}
                partial_config = make_batch_config(conf, [batch_entry])
                partial_report = yt.scan(partial_config)
                if partial_report['errors'] or len(partial_report['podcasts']) != 1:
                    raise RuntimeError('Scansione YouTube/Apple incompleta: ' + str(partial_report['errors'])[:190])
                youtube_success.append(batch_entry)
                youtube_reports.append(partial_report['podcasts'][0])
                status = 'SCANSIONATO'
                print(f'  Candidati forti: {partial_report["totalStrongCandidates"]}', flush=True)
        except (ValueError, OSError, RuntimeError, urllib.error.URLError, json.JSONDecodeError) as exc:
            record['lastError'] = str(exc)[:230]
            print('  AVVISO:', str(exc)[:200], flush=True)
            status = 'ERRORE'
        record['status'] = status
        state['shows'][cid] = record
        logs.append({'appleCollectionId': cid, 'name': record.get('name'),
                     'status': status, 'youtubeChannelId': record.get('youtubeChannelId', ''),
                     'channelProof': record.get('channelProof', ''),
                     'error': record.get('lastError', '') if status == 'ERRORE' else ''})

    batch_config = make_batch_config(conf, youtube_success)
    batch_report = empty_yt_report()
    batch_report.update({
        'podcasts': youtube_reports,
        'showsConfigured': len(youtube_success),
        'showsAnalyzed': len(youtube_success),
        'totalStrongCandidates': sum(x['strongCandidates'] for x in youtube_reports),
        'totalToReview': sum(x['toReview'] for x in youtube_reports),
    })
    preview = preview_batch(batch_report, catalog, batch_config)
    summary = {
        'mode': 'SOLO_SIMULAZIONE', 'generatedAt': iso_now(),
        'scope': 'catalogo MerON facoltativo + classifiche Apple + ID aggiuntivi + canali noti',
        'podcastUniciNellaCoda': len(sources) - len(excludes & sources.keys()),
        'podcastControllatiInQuestoLotto': examined,
        'canaliYoutubeControllatiInQuestoLotto': youtube_scanned,
        'canaliDocumentatiV4Scansionati': canali_documentati_scansionati,
        'canaliYoutubeScansionatiConSuccesso': len(youtube_success),
        'trovatiSenzaCanaleVerificabile': sum(r['status'] == 'SENZA_CANALE_VERIFICABILE' for r in logs),
        'podcastRiesaminatiConRicercaMigliorata': riesaminati,
        'versioneRicercaCanali': DISCOVERY_REVISION,
        'lottoFermatoPerTempo': stopped_for_time,
        'erroriInQuestoLotto': sum(r['status'] == 'ERRORE' for r in logs),
        'podcastGiaControllatiNelloStato': len(state['shows']),
        'candidatiFortiNuovoLotto': batch_report['totalStrongCandidates'],
        'daVerificareNuovoLotto': batch_report['totalToReview'],
        'nuoviCollegamentiProposti': len(preview['selected']),
        'sospesiPerSicurezza': len(preview['held']),
        'giaPresentiIdentici': len(preview['existing']),
        'catalogoPrima': len(catalog['videos']),
        'catalogoDopo': len(catalog['videos']),
        'chartErrors': chart_errors,
        'videoCatalogoModificato': False,
    }
    output = {'summary': summary, 'thisRun': logs,
              'currentBatch': {'configuredPodcasts': youtube_success},
              'instructions': ['Sola simulazione. Non modificare videos.json.',
                               'I canali assenti non sono prova che il podcast non abbia video.',
                               'I risultati su YouTube dipendono dalla disponibilita del canale e da yt-dlp.']}

    atomic_json(STATE_FILE, state)
    atomic_json(DYNAMIC_CONFIG_FILE, batch_config)
    atomic_json(YOUTUBE_REPORT_FILE, batch_report)
    atomic_json(DETAIL_FILE, preview)
    atomic_json(SUMMARY_FILE, output)
    with CSV_FILE.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(['podcast', 'appleTrackId', 'episode', 'status', 'youtubeUrl', 'score', 'reason'])
        for obj in preview['selected']:
            r = obj['record']
            writer.writerow([r['podcast'], obj['trackId'], r['episode'], 'PROPOSTA',
                             r['youtubeUrl'], obj['score'], r['matchRule']])
        for obj in preview['held']:
            writer.writerow([obj.get('podcast'), obj.get('trackId'), obj.get('episode'),
                             'SOSPESO', obj.get('youtubeUrl'), obj.get('score'), obj['reason']])
    if (BASE / 'videos.json').read_bytes() != original_catalog:
        raise RuntimeError('videos.json modificato durante la scansione: controllo fallito')
    print('\nMERON - RICERCA VIDEO DI TUTTI I PODCAST (A LOTTI)', flush=True)
    for key, value in summary.items():
        if key != 'chartErrors':
            print(f'{key}: {value}', flush=True)
    print('CANALE NON VERIFICABILE NON VUOL DIRE NESSUN VIDEO.', flush=True)
    print('videos.json INALTERATO. Nessun collegamento pubblicato.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
