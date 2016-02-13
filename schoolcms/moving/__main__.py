#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SchoolCMS util.

Move old_ann_system to SchoolCMS.
Terminal Tool.

"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

from .movinglog import MovingLog
from ..db import SessionGen, Announce, Record, AttachmentList

import logging
import requests
import os
import re
import uuid
import shutil
import subprocess
import mimetypes
from bs4 import BeautifulSoup
from datetime import datetime, timedelta

from tornado.options import options


mytid_re    = re.compile(r'mytid=([0-9]+)')
time_re     = re.compile(r'([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})(?: \(最新編修時間 ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\))?')
att_link_re = re.compile(r'^相關附件[0-9]：([\S]+) \(大小：[\S]+ 時間：([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})\)$')


def _get_content_type(filename, real_filename=''):
    _content_type, encoding = mimetypes.guess_type(real_filename)
    if not _content_type:
        _content_type = subprocess.check_output('file -b --mime-type %s' % filename, shell=True)
        _content_type = re.search(r'([\S]+)', _content_type).group()
    return _content_type


def _update_att(ann_trs, ann_id):
    old_atts = AttachmentList.by_ann_id(ann_id, sql_session).all()
    for old_att in old_atts:
        shutil.rmtree('file/%s' % old_att.key)
    AttachmentList.by_ann_id(ann_id, sql_session).delete()
    for tr in ann_trs[4:]:
        a = tr.find('a')
        if not a:
            continue
        m = att_link_re.match(a.text)
        if m:
            att_key = '%s' % uuid.uuid1().hex
            att_name = m.group(1)
            att_time = datetime.strptime(m.group(2), '%Y-%m-%d %H:%M:%S') - timedelta(hours=8)

            os.makedirs('file/%s' % att_key)
            r = requests.get(a['href'], stream=True)
            with open('file/%s/%s' % (att_key, att_name), 'wb') as f:
                for chunk in r.iter_content(chunk_size=1024): 
                    if chunk: # filter out keep-alive new chunks
                        f.write(chunk)
                        f.flush()
            att_content_type = _get_content_type('file/%s/%s' % (att_key, att_name), att_name)
            sql_session.add(AttachmentList(att_key, ann_id, att_content_type, att_name))


def _parse_ann(ann_trs, ann_url, movinglog, mytid, ann_time):
    title = ann_trs[1].find_all('td')[0].find('font').text
    content = ann_trs[3].find('td').find('font').text
    author_group_name = ann_trs[0].find_all('td')[0].find('font').text
    author_name = ann_trs[0].find_all('td')[1].find('font').text

    addition_content = '''

***
這篇公告從「Ann公告系統」讀取後自動同步。
因為該系統沒有排版功能，這篇公告可能會：
1.在奇怪的地方換行。
2.超連結包含奇怪的文字。(請手動去除多餘的字元)
本系統更新頻率為一小時一次，如有需要可以參考「[原系統公告連結](%s)」。

''' % ann_url

    for tr in ann_trs[4:]:
        a = tr.find('a')
        if att_link_re.match(a.text):
            break
        content += '\n * [%s](%s)' % (a.text, a['href'])
    content += addition_content

    if movinglog:
        Announce.by_id(movinglog.id, sql_session).update({
                'title': title,
                'content': content,
                'author_group_name': author_group_name,
                'author_name': author_name,
            })
        MovingLog.by_mytid(mytid, sql_session).update({
                'time': ann_time,
            })
        Record.add('update', movinglog.id, sql_session)
    else:
        new_ann = Announce(title, content, author_group_name, author_name, ann_is_private, created=ann_time)
        sql_session.add(new_ann)
        sql_session.flush()
        sql_session.refresh(new_ann)
        movinglog = MovingLog(new_ann.id, mytid, ann_time)
        sql_session.add(movinglog)
        Record.add('new', new_ann.id, sql_session)

    _update_att(ann_trs, movinglog.id)


def parse_ann(ann_url, ann_is_private):
    rel = requests.get(ann_url)
    rel.encoding = 'utf8'
    soup = BeautifulSoup(rel.text, 'html.parser')
    ann_trs = soup.find_all('tr')

    mytid = int(mytid_re.search(ann_url).group(1))
    movinglog = MovingLog.by_mytid(mytid, sql_session).scalar()
    
    ann_time_s = ann_trs[2].find_all('td')[0].find('font').text
    m = time_re.match(ann_time_s)
    time_s = m.group(2) if m.group(2) else m.group(1)
    ann_time = datetime.strptime(time_s, '%Y-%m-%d %H:%M:%S') - timedelta(hours=8)


    if not movinglog or movinglog.time < ann_time or options.mv_update or ann_is_private:
        _parse_ann(ann_trs, ann_url, movinglog, mytid, ann_time)
        logging.info('Ann Update(mytid= %s )' % mytid)
    else: 
        logging.info('Ann Doesn\'t Need TO Update(mytid= %s )' % mytid)


with SessionGen() as sql_session:
    for page in xrange(options.mv_page):
        logging.info('Start Page %s' % page)
        rel = requests.get('%s?myday=999&show=%d' % (options.ann_system_url, page*20))
        rel.encoding = 'utf8'
        soup = BeautifulSoup(rel.text, 'html.parser')

        if len(soup.find_all('table')) == 1:
            logging.info('This Page Is Empty')
            continue
        post_trs = soup.find_all('table')[1].find_all('tr')[1:]
        for post_tr in post_trs:
            link = post_tr.find_all('td')[1]
            ann_url = link.find('a')['href']
            # private ann
            ann_is_private = '[內部]' in link.text
            logging.info('AnnURL %s' % ann_url)

            parse_ann(ann_url, ann_is_private)
            sql_session.commit()
