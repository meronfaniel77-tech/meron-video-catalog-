#!/usr/bin/env python3
"""MerON: scopre video nativi nei feed RSS ufficiali di altri podcast.

SOLO RICOGNIZIONE: non importa video su videos.json, non modifica il catalogo Elisa.
Nessuna ricerca libera su YouTube: evita canali non ufficiali e abbinamenti errati.
"""
import argparse
import ipaddress
import json
import re
import socket
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
MAX_DOWNLOAD = 3 * 1024 * 1024
USER_AGENT = 'MerONVideoDiscovery/1.0 (podcast RSS verification)'
VIDEO_TYPES = {'video/mp4', 'video/webm', 'video/quicktime', 'application/vnd.apple.mpegurl',
               'application/x-mpegurl', 'application/dash+xml'}


def validate_url(url, video=False):
    """Accept only public HTTPS URLs. DNS validation also blocks private addresses."""
    if not isinstance(url, str):
        return False
    try:
        p = urllib.parse.urlsplit(url)
        h = (p.hostname or '').lower().rstrip('.')
        if p.scheme != 'https' or not h or p.username or p.password or p.port not in (None, 443):
            return False
        if h in {'localhost'} or h.endswith(('.localhost', '.local', '.internal')):
            return False
        try:
            ip = ipaddress.ip_address(h)
            if not ip.is_global:
                return False
        except ValueError:
            pass
        if video:
            return True  # Link returned as data; never followed by this program.
        # Reject domain names that resolve only to non-global IP addresses.
        for a in socket.getaddrinfo(h, 443, type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(a[4][0]).is_global:
                return False
        return True
    except (ValueError, OSError, OverflowError, TypeError):
        return False


class ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not validate_url(newurl):
            raise ValueError('Redirect verso indirizzo non pubblico')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


opener = urllib.request.build_opener(ValidatingRedirectHandler())


def fetch_bytes(url):
    if not validate_url(url):
        raise ValueError('URL non HTTPS/pubblico')
    request = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT, 'Accept': 'application/json, application/xml, text/xml, */*'})
    with opener.open(request, timeout=13) as resp:
        data = resp.read(MAX_DOWNLOAD + 1)
    if len(data) > MAX_DOWNLOAD:
        raise ValueError('Feed troppo grande')
    return data


def fetch_json(url):
    return json.loads(fetch_bytes(url).decode('utf-8-sig'))


def norm(text):
    text = unicodedata.normalize('NFKD', str(text or '').casefold())
    text = ''.join(c for c in text if not unicodedata.combining(c))
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', text)).strip()


def local(tag):
    return str(tag).rsplit('}', 1)[-1].lower()


def child_text(node, name):
    for child in node:
        if local(child.tag) == name:
            return (child.text or '').strip()
    return ''


def is_video_media(url, typ, medium=''):
    typ = (typ or '').lower().split(';')[0].strip()
    return (bool(url) and validate_url(url, video=True) and (
        typ.startswith('video/') or typ in VIDEO_TYPES or medium.lower() == 'video'
    ))


def video_sources(item):
    """RSS enclosure, Media RSS and Podcasting 2.0 alternateEnclosure."""
    matches = []
    for element in item.iter():
        kind = local(element.tag)
        if kind in ('enclosure', 'content'):
            url = element.get('url', '')
            typ = element.get('type', '')
            medium = element.get('medium', '')
            if is_video_media(url, typ, medium):
                matches.append({'url': url, 'mimeType': typ or 'video/*', 'protocol': kind})
        elif kind == 'alternateenclosure':
            typ = element.get('type', '')
            for source in element:
                if local(source.tag) != 'source':
                    continue
                url = source.get('uri') or source.get('url') or ''
                source_typ = source.get('type') or typ
                if is_video_media(url, source_typ):
                    matches.append({'url': url, 'mimeType': source_typ, 'protocol': 'alternateEnclosure'})
    seen = set()
    out = []
    for match in matches:
        if match['url'] not in seen:
            out.append(match)
            seen.add(match['url'])
    # Prefer downloadable files over adaptive playlists.
    out.sort(key=lambda x: (0 if x['mimeType'].lower().startswith('video/') else 1, x['url']))
    return out


def read_feed(data, max_episodes):
    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper():
        raise ValueError('DTD o entita XML non consentite')
    root = ET.fromstring(data)
    items = [e for e in root.iter() if local(e.tag) in ('item', 'entry')]
    video_episodes = []
    for item in items[:max_episodes]:
        sources = video_sources(item)
        if sources:
            title = child_text(item, 'title')
            guid = child_text(item, 'guid') or child_text(item, 'id')
            published = child_text(item, 'pubdate') or child_text(item, 'published')
            video_episodes.append({
                'title': title, 'guid': guid, 'published': published,
                'videoUrl': sources[0]['url'], 'mediaType': sources[0]['mimeType'],
                'source': 'feed_ufficiale', 'otherVideoSources': sources[1:],
            })
    return len(items), video_episodes


def apple_episodes_for_id(podcast_id):
    url = ('https://itunes.apple.com/lookup?id=' + urllib.parse.quote(podcast_id)
           + '&entity=podcastEpisode&country=IT&limit=200')
    return [x for x in fetch_json(url).get('results', [])
            if x.get('wrapperType') == 'podcastEpisode' or x.get('kind') == 'podcast-episode']


def link_apple_ids(podcast_id, episodes):
    try:
        apple = apple_episodes_for_id(podcast_id)
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError):
        return
    by_title = {}
    for e in apple:
        title = norm(e.get('trackName'))
        if title:
            by_title.setdefault(title, []).append(e)
    for e in episodes:
        matches = by_title.get(norm(e['title']), [])
        # No arbitrary match when more than one episode uses the same title.
        if len(matches) == 1 and isinstance(matches[0].get('trackId'), int):
            e['appleTrackId'] = matches[0]['trackId']


def top_podcasts(limit):
    url = f'https://itunes.apple.com/it/rss/toppodcasts/limit={limit}/json'
    feed = fetch_json(url).get('feed', {})
    found = []
    for item in feed.get('entry', []):
        iid = str(item.get('id', {}).get('attributes', {}).get('im:id', ''))
        if not iid.isdecimal():
            continue
        found.append({'id': iid, 'name': item.get('im:name', {}).get('label', ''),
                      'artist': item.get('im:artist', {}).get('label', '')})
    return found


def lookup_show(podcast_id):
    url = f'https://itunes.apple.com/lookup?id={podcast_id}&country=IT'
    results = fetch_json(url).get('results', [])
    for item in results:
        if str(item.get('collectionId')) == podcast_id and item.get('feedUrl'):
            return {'id': podcast_id, 'name': item.get('collectionName', ''),
                    'artist': item.get('artistName', ''), 'feedUrl': item['feedUrl']}
    raise ValueError('Feed RSS non trovato su Apple')


def scan(config, fetch=fetch_bytes):
    top_limit = max(1, min(int(config.get('topPodcastLimit', 40)), 100))
    max_episodes = max(1, min(int(config.get('maxEpisodesPerPodcast', 120)), 500))
    max_podcasts = max(1, min(int(config.get('maxPodcastsPerRun', 40)), 150))
    excludes = {str(x) for x in config.get('excludePodcastIds', [])}
    shows = []
    errors = []
    try:
        shows = top_podcasts(top_limit)
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        errors.append({'show': 'classifica Apple', 'error': str(exc)[:200]})
    for show_id in config.get('extraPodcastIds', []):
        if str(show_id).isdecimal():
            shows.append({'id': str(show_id), 'name': '', 'artist': ''})
    unique = []
    seen = set()
    for s in shows:
        if s['id'] not in seen and s['id'] not in excludes:
            seen.add(s['id'])
            unique.append(s)
    unique = unique[:max_podcasts]
    scanned = []
    with_video = []
    for i, s in enumerate(unique, 1):
        label = s.get('name') or s['id']
        print(f'[{i}/{len(unique)}] {label}', flush=True)
        try:
            show = lookup_show(s['id'])
            if not validate_url(show['feedUrl']):
                raise ValueError('RSS non HTTPS/pubblico: non importato')
            count, episodes = read_feed(fetch(show['feedUrl']), max_episodes)
            summary = {'collectionId': s['id'], 'name': show['name'],
                       'artist': show['artist'], 'feedUrl': show['feedUrl'],
                       'episodesInFeed': count, 'episodesExamined': min(count, max_episodes),
                       'nativeVideoEpisodes': len(episodes)}
            scanned.append(summary)
            if episodes:
                link_apple_ids(s['id'], episodes)
                with_video.append({**summary, 'videoEpisodes': episodes})
            print(f'  episodi={min(count,max_episodes)}, video_RSS={len(episodes)}', flush=True)
        except (ValueError, OSError, ET.ParseError, urllib.error.URLError, json.JSONDecodeError) as exc:
            errors.append({'collectionId': s['id'], 'show': label, 'error': str(exc)[:240]})
            print(f'  AVVISO: {str(exc)[:150]}', flush=True)
    return {'generatedAt': datetime.now(timezone.utc).isoformat(),
            'mode': 'SOLO_RICOGNIZIONE', 'notes': [
                'Non modifica videos.json, non modifica il catalogo Elisa True Crime.',
                'Un video RSS e dichiarato dal feed, non necessariamente identico a una puntata audio.',
                'YouTube non esaminato: occorre associare prima il canale ufficiale di ciascun podcast.',
                'La classifica Apple non comprende tutti i podcast esistenti.',
            ], 'totalShowsExamined': len(scanned), 'showsWithNativeVideo': len(with_video),
            'totalNativeVideoEpisodes': sum(x['nativeVideoEpisodes'] for x in with_video),
            'videoPodcasts': with_video, 'allScannedPodcasts': scanned, 'errors': errors}


def main():
    p = argparse.ArgumentParser(description='MerON - scoperta video RSS per altri podcast')
    p.add_argument('--config', default=str(BASE / 'config_video_altri_podcast.json'))
    p.add_argument('--output', default=str(BASE / 'altri_podcast_video_report.json'))
    args = p.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf8'))
    result = scan(config)
    output = Path(args.output)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print('\nMERON - RICOGNIZIONE VIDEO ALTRI PODCAST', flush=True)
    for k in ('mode', 'totalShowsExamined', 'showsWithNativeVideo', 'totalNativeVideoEpisodes'):
        print(f'{k}: {result[k]}')
    print(f'errori_o_feed_non_accessibili: {len(result["errors"])}')
    print('Catalogo Elisa videos.json: INALTERATO')
    print('Report:', output.name)
    # Fail if no input was actually inspected: avoid treating network outages as empty catalogs.
    if not result['totalShowsExamined']:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
