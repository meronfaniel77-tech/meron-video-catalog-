import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scopri_video_tutti_podcast as s

CHANNEL = 'UC' + 'A' * 22
CHANNEL2 = 'UC' + 'B' * 22


class UniversalVideoTests(unittest.TestCase):
    def test_config_validates_simulation_only(self):
        conf = json.loads((Path(__file__).parent / 'config_video_tutti_podcast.json').read_text())
        s.validate_config(conf)
        conf['mode'] = 'PUBBLICAZIONE_AUTOMATICA'
        with self.assertRaises(ValueError):
            s.validate_config(conf)

    def test_channel_extraction_ignores_videos(self):
        text = ('<a href="https://www.youtube.com/watch?v=0aaaaa11111">watch</a>'
                ' <a href="https://www.youtube.com/@podcastesempio/videos">official</a>'
                ' <a href="https://youtube.com/channel/' + CHANNEL + '/videos">channel</a>')
        self.assertEqual(s.extract_channels(text),
                         ['https://www.youtube.com/@podcastesempio',
                          'https://www.youtube.com/channel/' + CHANNEL])

    def test_feed_meta_only_header(self):
        raw = ('<?xml version="1.0"?><rss><channel><title>Nome</title>'
               '<link>https://podcast.example.com</link>'
               '<description>https://youtube.com/@ufficiale</description>'
               '<item><description>https://www.youtube.com/@ospite</description></item>'
               '</channel></rss>').encode()
        site, urls = s.rss_channel_meta(raw)
        self.assertEqual(site, 'https://podcast.example.com')
        self.assertEqual(urls, ['https://www.youtube.com/@ufficiale'])

    def test_feed_link_is_preferred_to_site(self):
        rss = (b'<rss><channel><link>https://sito.example.com</link>'
               b'<description>https://www.youtube.com/@ufficiale</description><item>')
        with patch.object(s, 'public_https', return_value=True):
            link, proof = s.choose_official_channel(
                {'feedUrl': 'https://feed.example.com/rss'},
                get=lambda url, size, timeout: rss)
        self.assertEqual(link, 'https://www.youtube.com/@ufficiale')
        self.assertEqual(proof, 'LINK_NEL_FEED_APPLE')

    def test_multiple_site_channels_stays_unverified(self):
        rss = b'<rss><channel><link>https://sito.example.com</link><item>'
        page = (b'<a href="https://www.youtube.com/@audiopodcast"></a>'
                b'<a href="https://www.youtube.com/@guestpodcast"></a>')
        with patch.object(s, 'public_https', return_value=True):
            link, proof = s.choose_official_channel(
                {'feedUrl': 'https://feed.example.com/rss'},
                get=lambda url, size, timeout: rss if 'feed.' in url else page)
        self.assertIsNone(link)
        self.assertEqual(proof, 'PIU_CANALI_YOUTUBE_SUL_SITO')

    def test_private_network_blocked(self):
        for url in ('http://foo.example.com/x', 'https://localhost/',
                    'https://127.0.0.1/', 'https://169.254.169.254/',
                    'https://[::1]/', 'file:///etc/passwd'):
            self.assertFalse(s.public_https(url))

    def test_state_rescan_scheduler(self):
        conf = json.loads((Path(__file__).parent / 'config_video_tutti_podcast.json').read_text())
        recent = {'status': 'SENZA_CANALE_VERIFICABILE', 'lastAttempt': s.iso_now()}
        self.assertFalse(s.status_due(recent, conf))
        self.assertTrue(s.status_due({'status': 'DA_SCANSIONARE', 'lastAttempt': s.iso_now()}, conf))
        self.assertTrue(s.status_due(None, conf))

    def test_read_charts_deduplicates(self):
        conf = json.loads((Path(__file__).parent / 'config_video_tutti_podcast.json').read_text())
        conf['genres'] = ['1303']
        sample = {'feed': {'entry': [
            {'id': {'attributes': {'im:id': '123456789'}}, 'im:name': {'label': 'Esempio'}}]}}
        with patch.object(s, 'apple_get', return_value=sample) as f:
            shows, errors = s.read_charts(conf)
        self.assertEqual(list(shows), ['123456789'])
        self.assertEqual(errors, [])
        self.assertEqual(f.call_count, 2)

    def test_catalog_never_changes_and_run_is_incremental(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            config = json.loads((Path(__file__).parent / 'config_video_tutti_podcast.json').read_text())
            config.update({'genres': [], 'additionalPodcastIds': [],
                           'maxShowsPerRun': 2, 'maxYoutubeChannelsPerRun': 2})
            (root / 'config_video_tutti_podcast.json').write_text(json.dumps(config))
            (root / 'config_youtube_altri_podcast.json').write_text('{"podcasts":[]}')
            catalog_bytes = b'{"videos":{"1":{"podcast":"Elisa True Crime","youtubeUrl":"https://www.youtube.com/watch?v=123456789ab"}}}'
            (root / 'videos.json').write_bytes(catalog_bytes)
            urls = {'10101010': {'name': 'Pod Uno', 'source': 'chart'},
                    '20202020': {'name': 'Pod Due', 'source': 'chart'}}
            mock_report = {
                'podcasts': [{
                    'name': 'Pod Uno', 'appleCollectionId': '10101010',
                    'youtubeChannelId': CHANNEL, 'appleEpisodesRead': 0,
                    'youtubeVideosRead': 1, 'strongCandidates': 0, 'toReview': 0,
                    'noCandidate': 0, 'proposals': []}],
                'errors': [], 'totalStrongCandidates': 0, 'totalToReview': 0
            }
            def show(cid, country):
                return {'name': 'Pod Uno' if cid == '10101010' else 'Pod Due',
                        'feedUrl': 'https://fake.example/feed'}
            def channel(doc):
                if doc['name'] == 'Pod Uno':
                    return 'https://www.youtube.com/channel/' + CHANNEL, 'FEED'
                return None, 'NESSUNO'
            patch_paths = {
                'BASE': root,
                'STATE_FILE': root / 'stato_video_tutti_podcast.json',
                'CONFIG_FILE': root / 'config_video_tutti_podcast.json',
                'SUMMARY_FILE': root / 'rapporto_video_tutti_podcast.json',
                'DETAIL_FILE': root / 'anteprima_video_tutti_podcast.json',
                'CSV_FILE': root / 'anteprima_video_tutti_podcast.csv',
                'DYNAMIC_CONFIG_FILE': root / 'config_batch_video_tutti_podcast.json',
                'YOUTUBE_REPORT_FILE': root / 'rapporto_youtube_batch_tutti_podcast.json',
            }
            with patch.multiple(s, **patch_paths), \
                 patch.object(s, 'read_charts', return_value=(urls, [])), \
                 patch.object(s, 'apple_show', side_effect=show), \
                 patch.object(s, 'choose_official_channel', side_effect=channel), \
                 patch.object(s, 'resolve_channel', return_value=CHANNEL), \
                 patch.object(s.yt, 'scan', return_value=mock_report):
                self.assertEqual(s.main(), 0)
                summary = json.loads((root / 'rapporto_video_tutti_podcast.json').read_text())['summary']
                self.assertEqual(summary['podcastControllatiInQuestoLotto'], 2)
                self.assertEqual(summary['trovatiSenzaCanaleVerificabile'], 1)
                self.assertEqual(summary['canaliYoutubeScansionatiConSuccesso'], 1)
                self.assertEqual(s.main(), 0)
                summary = json.loads((root / 'rapporto_video_tutti_podcast.json').read_text())['summary']
                self.assertEqual(summary['podcastControllatiInQuestoLotto'], 0)
            self.assertEqual((root / 'videos.json').read_bytes(), catalog_bytes)


if __name__ == '__main__':
    unittest.main(verbosity=2)
