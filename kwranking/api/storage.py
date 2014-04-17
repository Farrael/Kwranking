# -*- coding: utf-8 -*-
#
# Author: Mouchel Thomas <thomspirit@gmail.com>
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import threading
import time
import random

from oslo.config import cfg
from ceilometerclient import client as ceilometer_client
import keystoneclient.middleware.auth_token as auth_token
import keystoneclient.v2_0 as keystone_client

app_opts = [
    cfg.IntOpt('refresh_interval',
               required=True,
               ),
]

cfg.CONF.register_opts(app_opts)

class Host(dict):
    """Contains fields (Wmin, Wmax, Flop) """

    def __init__(self, wmin, wmax, flop):
        """Initializes fields with the given arguments."""
        dict.__init__(self)
        self._dict          = {}
        self['Wmin']        = wmin
        self['Wmax']        = wmax
        self['Flop']        = flop
        self['Efficiency']  = flop / wmax
        self['Timestamp']   = int(round(time.time()))

    def update(self, wmin, wmax, flop):
        """Update field with the given arguments."""
        self['Wmin']        = wmin
        self['Wmax']        = wmax
        self['Flop']        = flop
        self['Efficiency']  = flop / wmax
        self['Timestamp']   = int(round(time.time()))

class Storage(dict):
    """Storage gradually fills its database with received values from Ceilometer and Climate API"""

    def __init__(self):
        """Initializes an empty database."""
        self._dict       = {}
        self['lock']     = threading.Lock()
        self['database'] = {}
        self['list']     = {}
        self['sorted']   = {}
        self['wait']     = []

    def wait(self, host):
        """Add host id to waiting list"""
        self['wait'].append(host)

    def add(self, host, wmin, wmax, flop):
        """Creates (or updates) ranking data for this host."""
        if host in self['database'].keys():
            self['database'][host].update(wmin, wmax, flop)
        else:
            record = Host(wmin, wmax, flop)
            self['database'][host] = record

        for method in self['sorted']:
            self['sorted'][method] = False

    def remove(self, host):
        """Removes this host from database."""
        try:
            del self['database'][host]
            return True
        except KeyError:
            return False

    def isSorted(self, method):
        """Return if list <method> is sorted"""
        return (method in self['sorted'] and self['sorted'][method])

    def sort(self, method):
        """Sort database by <method>."""
        try:
            sorted_list = sorted(self['database'], key=lambda x: self['database'][x][method], 
                                                reverse= True if(method == "Flop" or method == "Efficiency") else False)
        except Exception, e:
            return False

        self['list'][method]   = sorted_list
        self['sorted'][method] = True
        return True

    def refresh(self):

        # Host information will be collected
        def run_test(host_id):
            info = ceilo.statistics.list('power', q=[{'field':'resource', 'op':'eq', 'value':host_id}])
            if(len(info) >= 1):
                wmax = info[0].max
                wmin = info[0].min
                flop = random.uniform(0, 5)
                self.add(host_id, wmin, wmax, flop)

        # Keystone identification
        ks = keystone_client.Client(username=cfg.CONF.keystone_authtoken['admin_user'],
                        password=cfg.CONF.keystone_authtoken['admin_password'],
                        tenant_name=cfg.CONF.keystone_authtoken['admin_tenant_name'],
                        auth_url=cfg.CONF.keystone_authtoken['auth_uri'])

        endpoint = ks.service_catalog.url_for(service_type='metering',
                                              endpoint_type='publicURL')
        
        ceilo = ceilometer_client.Client('2', endpoint,
                                 token=(lambda: ks.auth_token))

        # Database Update
        for host_id in self['database']:
            host = self['database'][host_id]
            if( int(round(time.time() - host['Timestamp'])) >= cfg.CONF.refresh_interval):
                run_test(host_id)

        # Waiting list
        remove_list = []
        for host_id in self['wait']:
            info = ceilo.statistics.list('power', q=[{'field':'resource', 'op':'eq', 'value':host_id}])
            if(len(info) >= 1):
                run_test(host_id)
                remove_list.append(host_id)

        self['wait'] = list(set(self['wait']) - set(remove_list))

        # Schedule periodic execution of this function
        if cfg.CONF.refresh_interval > 0:
            timer = threading.Timer(cfg.CONF.refresh_interval, self.refresh)
            timer.daemon = True
            timer.start()