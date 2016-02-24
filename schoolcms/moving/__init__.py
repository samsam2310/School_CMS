#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""SchoolCMS util.

Move old_ann_system to SchoolCMS.
Terminal Tool.

Add att.

DB version -108
"""

from __future__ import absolute_import
from __future__ import print_function
from __future__ import unicode_literals

from tornado.options import define, options
define('ann_system_url', default='', help='', type=unicode)
define('mv_page', default=0, help='', type=int)
define('mv_update', default=False, help='', type=bool)

from ..util.parse_config import parse_config
parse_config()

version = '0.0.2'
