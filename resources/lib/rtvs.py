# -*- coding: UTF-8 -*-
# /*
# *      Copyright (C) 2013 Maros Ondrasek
# *
# *
# *  This Program is free software; you can redistribute it and/or modify
# *  it under the terms of the GNU General Public License as published by
# *  the Free Software Foundation; either version 2, or (at your option)
# *  any later version.
# *
# *  This Program is distributed in the hope that it will be useful,
# *  but WITHOUT ANY WARRANTY; without even the implied warranty of
# *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# *  GNU General Public License for more details.
# *
# *  You should have received a copy of the GNU General Public License
# *  along with this program; see the file COPYING.  If not, write to
# *  the Free Software Foundation, 675 Mass Ave, Cambridge, MA 02139, USA.
# *  http://www.gnu.org/copyleft/gpl.html
# *
# */

import re
import os
import urllib
import shutil
import traceback
from http import cookiejar
import hashlib
import calendar
from time import sleep
from datetime import date
import util
from provider import ContentProvider
import json
import xbmc, xbmcaddon, xbmcgui

START_AZ = '<div class=\"row tv__archive tv__archive--list\">'
END_AZ = '<div class="footer'
AZ_ITER_RE = '<a title=\"(?P<title>[^"]+)\"(.+?)href=\"(?P<url>[^"]+)\"(.+?)<img src=\"(?P<img>[^"]+)\"(.+?)<span class=\"date\">(?P<date>[^<]+)<\/span>(.+?)<span class=\"program time--start\">(?P<time>[^<]+)'

START_DATE = '<div class=\"row tv__archive tv__archive--date\" data-js-tabs>'
END_DATE = END_AZ
DATE_ITER_RE = '<div class=\"media\">\s*<a href=\"(?P<url>[^\"]+)\"[^<]+>\s*<img src=\"(?P<img>[^\"]+)\".+?<\/a>\s*<div class=\"media__body\">.+?<div class=\"program time--start\">(?P<time>[^\<]+)<span>.+?<a class=\"link\".+?title=\"(?P<title>[^\"]+)\">.+?<\/div>'

START_LISTING = "<div class='calendar modal-body'>"
END_LISTING = '</table>'
LISTING_PAGER_RE = "<a class=\'prev calendarRoller' href=\'(?P<prevurl>[^\']+)\'.+?<a class=\'next calendarRoller\' href=\'(?P<nexturl>[^\']+)"
LISTING_DATE_RE = '<div class=\'calendar-header\'>\s+.*?<h6>(?P<date>[^<]+)</h6>'
LISTING_ITER_RE = '<td class=(\"day\"|\"active day\")>\s+<a href=[\'\"](?P<url>[^\"^\']+)[\"\']>(?P<daynum>[\d]+)</a>\s+</td>'

EPISODE_RE = '<div class=\"article-header\">\s+?<h2>(?P<title>[^<]+)</h2>.+?(<div class=\"span6">\s+?<div[^>]+?>(?P<plot>[^<]+)</div>)?'

def to_unicode(text, encoding='utf-8'):
    return text

def get_streams_from_manifest_url(url):
    result = []
    manifest = util.request(url)
    for m in re.finditer(r'^#EXT-X-STREAM-INF:(?P<info>.+)\n(?P<chunk>.+)', manifest, re.MULTILINE):
        stream = {}
        stream['quality'] = '???'
        stream['bandwidth'] = 0
        for info in re.split(r''',(?=(?:[^'"]|'[^']*'|"[^"]*")*$)''', m.group('info')):
            key, val = info.split('=', 1)
            if key == "BANDWIDTH":
                stream['bandwidth'] = int(val)
            if key == "RESOLUTION":
                stream['quality'] = val.split("x")[1] + "p"
        stream['url'] = url[url.find(':')+1:url.find('/')] + m.group('chunk')
        result.append(stream)
    result.sort(key=lambda x:x['bandwidth'], reverse=True)
    return result

def is_kodi_leia():
    version = re.split("[, \-!?:]+", xbmc.getInfoLabel('System.BuildVersion'))[0]
    if (float(version) >= 18):
        #chceck if is inputstream.adaptive present
        payload = {'jsonrpc': '2.0','id': 1,'method': 'Addons.GetAddonDetails','params': {'addonid': 'inputstream.adaptive','properties': ['enabled']}}
        response = xbmc.executeJSONRPC(json.dumps(payload))
        data = json.loads(response)
        print(data)
        if ('error' not in data.keys() and 
                'result' in data.keys() and 
                'addon' in data['result'].keys() and 
                'enabled' in data['result']['addon'].keys() and 
                data['result']['addon']['enabled']):
            return True
        else:
            scriptid = 'plugin.video.rtvs.sk'
            addon = xbmcaddon.Addon(id=scriptid)
            xbmcgui.Dialog().ok(addon.getLocalizedString(31010), addon.getLocalizedString(31011), addon.getLocalizedString(31012), addon.getLocalizedString(31013))
    return False

class RtvsContentProvider(ContentProvider):

    def __init__(self, username=None, password=None, filter=None, tmp_dir='/tmp'):
        ContentProvider.__init__(self, 'rtvs.sk', 'http://www.rtvs.sk/televizia/archiv', username, password, filter, tmp_dir)
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cookiejar.LWPCookieJar()))
        urllib.request.install_opener(opener)
        if not os.path.exists(self.tmp_dir):
            os.makedirs(self.tmp_dir)

    def _fix_url(self, url):
        if url.startswith('/json/') or url.startswith('/televizia/archiv/'):
            return 'http://www.rtvs.sk' + url
        return self._url(url)

    def capabilities(self):
        return ['categories', 'resolve', '!download']

    def list(self, url):
        if url.find('#az#') == 0:
            return self.az()
        if url.find('#live#') == 0:
            return self.live()
        elif url.find("#date#") == 0:
            month, year = url.split('#')[-1].split('.')
            return self.date(int(year), int(month))
        elif url.find('ord=az') != -1 and url.find('l=') != -1:
            self.info('AZ listing: %s' % url)
            return self.list_az(util.request(self._fix_url(url)))
        elif url.find('ord=dt') != -1 and url.find('date=') != -1:
            self.info('DATE listing: %s' % url)
            return self.list_date(util.request(self._fix_url(url)))
        elif url.find('/json/') != -1:
            if url.find('snippet_archive_series_calendar.json'):
                self.info("EPISODE listing (JSON): %s" % url)
                return self.list_episodes(util.json.loads(util.request(self._fix_url(url)))['snippets']['snippet-calendar-calendar'])
            else:
                self.error("unknown JSON listing request: %s"% url)
        else:
            self.info("EPISODE listing: %s" % url)
            return self.list_episodes(util.request(self._fix_url(url)))

    def categories(self):
        result = []
        item = self.dir_item()
        item['title'] = '[B]A-Z[/B]'
        item['url'] = "#az#"
        result.append(item)
        item = self.dir_item()
        item['title'] = '[B]Podľa dátumu[/B]'
        d = date.today()
        item['url'] = "#date#%d.%d" % (d.month, d.year)
        result.append(item)
        item = self.dir_item()
        item['title'] = '[B]Živé vysielanie[/B]'
        item['url'] = "#live#"
        result.append(item)
        return result

    def live(self):
        result = []
        item = self.video_item("live.1")
        item['title'] = "STV 1"
        result.append(item)
        item = self.video_item("live.2")
        item['title'] = "STV 2"
        result.append(item)
        item = self.video_item("live.3")
        item['title'] = "STV 3"
        result.append(item)
        item = self.video_item("live.4")
        item['title'] = "STV Online"
        result.append(item)
        item = self.video_item("live.5")
        item['title'] = "STV NRSR"
        result.append(item)
        return result

    def az(self):
        result = []
        item = self.dir_item()
        item['title'] = '0-9'
        item['url'] = '?l=9&ord=az'
        self._filter(result, item)
        for c in range(65, 91, 1):
            uchr = str(chr(c))
            item = self.dir_item()
            item['title'] = uchr
            item['url'] = '?l=%s&ord=az' % uchr.lower()
            self._filter(result, item)
        return result

    def date(self, year, month):
        result = []
        today = date.today()
        prev_month = month > 0 and month - 1 or 12
        prev_year = prev_month == 12 and year - 1 or year
        item = self.dir_item()
        item['type'] = 'prev'
        item['url'] = "#date#%d.%d" % (prev_month, prev_year)
        result.append(item)
        for d in calendar.LocaleTextCalendar().itermonthdates(year, month):
            if d.month != month:
                continue
            if d > today:
                break
            item = self.dir_item()
            item['title'] = "%d.%d %d" % (d.day, d.month, d.year)
            item['url'] = "?date=%d-%02d-%02d&ord=dt" % (d.year, d.month, d.day)
            self._filter(result, item)
        result.reverse()
        return result

    def list_az(self, page):
        result = []
        images = []
        page = util.substr(page, START_AZ, END_AZ)
        for m in re.finditer(AZ_ITER_RE, page, re.IGNORECASE | re.DOTALL):
            img = {'remote':self._fix_url(m.group('img')),
                   'local' :self._get_image_path(self._fix_url(m.group('img')))}
            item = self.dir_item()
            semicolon = m.group('title').find(':')
            if semicolon != -1:
                item['title'] = m.group('title')[:semicolon].strip()
            else:
                item['title'] = m.group('title')
            item['img'] = img['local']
            item['url'] = m.group('url')
            self._filter(result, item)
            images.append(img)
        self._get_images(images)
        return result

    def list_date(self, page):
        result = []
        images = []
        page = util.substr(page, START_DATE, END_DATE)
        for m in re.finditer(DATE_ITER_RE, page, re.IGNORECASE | re.DOTALL):
            img = {'remote':self._fix_url(m.group('img')),
                   'local' :self._get_image_path(self._fix_url(m.group('img')))}
            item = self.video_item()
            item['title'] = "%s (%s)" % (m.group('title'), m.group('time'))
            item['img'] = img['local']
            item['url'] = m.group('url')
            item['menu'] = {'$30070':{'list':item['url'], 'action-type':'list'}}
            self._filter(result, item)
            images.append(img)
        self._get_images(images)
        return result

    def list_episodes(self, page):
        result = []
        episodes = []
        page = util.substr(page, START_LISTING, END_LISTING)
        current_date = to_unicode(re.search(LISTING_DATE_RE, page, re.IGNORECASE | re.DOTALL).group('date'))
        self.info("<list_episodes> current_date: %s" % current_date)
        prev_url = re.search(LISTING_PAGER_RE, page, re.IGNORECASE | re.DOTALL).group('prevurl')
        prev_url = re.sub('&amp;', '&', prev_url)
        #self.info("<list_episodes> prev_url: %s" % prev_url)
        for m in re.finditer(LISTING_ITER_RE, page, re.IGNORECASE | re.DOTALL):
            episodes.append([self._fix_url(re.sub('&amp;', '&', m.group('url'))), m])
        self.info("<list_episodes> found %d episodes" % len(episodes))
        res = self._request_parallel(episodes)
        for p, m in res:
            m = m[0]
            dnum = to_unicode(m.group('daynum'))
            item = self.list_episode(p)
            item['title'] = "%s (%s. %s)" % (item['title'], dnum, current_date)
            item['date'] = dnum
            item['url'] = re.sub('&amp;', '&', m.group('url'))
            self._filter(result, item)
        result.sort(key=lambda x:int(x['date']), reverse=True)

        item = self.dir_item()
        item['type'] = 'prev'
        item['url'] = prev_url
        self._filter(result, item)
        return result

    def list_episode(self, page):
        item = self.video_item()
        episode = re.search(EPISODE_RE, page, re.DOTALL)
        if episode:
            item['title'] = to_unicode(episode.group('title').strip())
            if episode.group('plot'):
                item['plot'] = to_unicode(episode.group('plot').strip())
        return item

    def resolve(self, item, captcha_cb=None, select_cb=None):
        result = []
        item = item.copy()
        if item['url'].startswith('live.'):
            channel_id = item['url'].split('.')[1]
            data = util.request("http://www.rtvs.sk/json/live5f.json?c=%s&b=mozilla&p=linux&v=47&f=1&d=1"%(channel_id))
            videodata = util.json.loads(data)['clip']
            url = videodata['sources'][0]['src']
            url = ''.join(url.split()) # remove whitespace \n from URL
            if is_kodi_leia():
                #return playlist with adaptive flag
                item = self.video_item()
                item['title'] = videodata.get('title','')
                item['url'] = url
                item['quality'] = 'adaptive'
                item['img'] = videodata.get('image','')
                result.append(item)
            else:
                #process m3u8 playlist
                for stream in get_streams_from_manifest_url(url):
                    item = self.video_item()
                    item['title'] = videodata.get('title','')
                    item['url'] = stream['url']
                    item['quality'] = stream['quality']
                    item['img'] = videodata.get('image','')
                    result.append(item)
        else:
            video_id = item['url'].split('/')[-1]
            self.info("<resolve> videoid: %s" % video_id)
            videodata = util.json.loads(util.request("https://www.rtvs.sk/json/archive5f.json?id=" + video_id))
            for v in videodata['clip']['sources']:
                url =  v['src']
                if '.m3u8' in url:
                    if is_kodi_leia():
                        #return playlist with adaptive flag
                        item = self.video_item()
                        item['title'] = videodata.get('title','')
                        item['surl'] = item['title']
                        item['quality'] = 'adaptive'
                        item['url'] = url
                        result.append(item)
                    else:
                        #process m3u8 playlist
                        for stream in get_streams_from_manifest_url(url):
                            item = self.video_item()
                            item['title'] = videodata.get('title','')
                            item['surl'] = item['title']
                            item['url'] = stream['url']
                            item['quality'] = stream['quality']
                            result.append(item)
        self.info("<resolve> playlist: %d items" % len(result))
        map(self.info, ["<resolve> item(%d): title= '%s', url= '%s'" % (i, it['title'], it['url']) for i, it in enumerate(result)])
        if len(result) > 0 and select_cb:
            return select_cb(result)
        return result

    def _request_parallel(self, requests):
        def fetch(req, *args):
            return util.request(req), args
        pages = []
        q = util.run_parallel_in_threads(fetch, requests)
        while True:
            try:
                page, args = q.get_nowait()
            except:
                break
            pages.append([page, args])
        return pages

    def _get_image_path(self, name):
        local = self.tmp_dir
        m = hashlib.md5()
        m.update(name.encode("utf-8"))
        image = os.path.join(local, m.hexdigest() + '_img.png')
        return image

    def _get_images(self, images):
        def download(remote, local):
            util.save_data_to_file(util.request(remote), local)
        not_cached = [(img['remote'], img['local'])
                       for img in images if not os.path.exists(img['local'])]
        util.run_parallel_in_threads(download, not_cached)
