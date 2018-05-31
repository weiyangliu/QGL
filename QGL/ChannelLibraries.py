'''
Channels is where we store information for mapping virtual (qubit) channel to
real channels.

Split from Channels.py on Jan 14, 2016.

Original Author: Colm Ryan

Copyright 2016 Raytheon BBN Technologies

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

   http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

Include modification to yaml loader (MIT License) from
https://gist.github.com/joshbode/569627ced3076931b02f

Scientific notation fix for yaml from
https://stackoverflow.com/questions/30458977/yaml-loads-5e-6-as-string-and-not-a-number
'''

import sys
import os
import re
import traceback
import datetime
import importlib
from pony.orm import *
import networkx as nx
import yaml

# FSEvents observer in watchdog cannot have multiple watchers of the same path
# use kqueue instead
if sys.platform == 'darwin':
    from watchdog.observers.kqueue import KqueueObserver as Observer
else:
    from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import time

from . import config
from . import Channels
from . import PulseShapes

channelLib = None

def set_from_dict(obj, settings):
    for prop_name in obj.to_dict().keys():
        if prop_name in settings.keys():
            try:
                setattr(obj, prop_name, settings[prop_name])
            except Exception as e:
                print(f"{obj.label}: Error loading {prop_name} from config")

class ChannelLibrary(object):

    def __init__(self, library_file=None, blank=False, channelDict={}, **kwargs):
        """Create the channel library. We assume that the user wants the config file in the 
        usual locations specified in the config files."""

        # Load the basic config options from the yaml
        self.library_file = config.load_config(library_file)

        self.connectivityG = nx.DiGraph()
        
        self.channelDict = {c.label: c for  c in select(c for c in Channels.Channel)}

        # Update the global reference
        global channelLib
        channelLib = self

    #Dictionary methods
    def __getitem__(self, key):
        return self.channelDict[key]

    def __setitem__(self, key, value):
        self.channelDict[key] = value

    def __delitem__(self, key):
        del self.channelDict[key]

    def __contains__(self, key):
        return key in self.channelDict

    def keys(self):
        return self.channelDict.keys()

    def values(self):
        return self.channelDict.values()

    def build_connectivity_graph(self):
        # build connectivity graph
        for chan in select(q for q in Channels.Qubit if q not in self.connectivityG):
            self.connectivityG.add_node(chan)
        for chan in select(e for e in Channels.Edge):
            self.connectivityG.add_edge(chan.source, chan.target)
            self.connectivityG[chan.source][chan.target]['channel'] = chan


def QubitFactory(label, **kwargs):
    ''' Return a saved qubit channel or create a new one. '''
    thing = select(el for el in Channels.Qubit if el.label==label).first()
    if thing:
        return thing
    else:
        return Channels.Qubit(label=label, **kwargs)
    
def MeasFactory(label, **kwargs):
    ''' Return a saved measurement channel or create a new one. '''
    thing = select(el for el in Channels.Measurement if el.label==label).first()
    if thing:
        return thing
    else:
        return Channels.Measurement(label=label, **kwargs)

def MarkerFactory(label, **kwargs):
    ''' Return a saved Marker channel or create a new one. '''
    thing = select(el for el in Channels.LogicalMarkerChannel if el.label==label).first()
    if thing:
        return thing
    else:
        return Channels.LogicalMarkerChannel(label=label, **kwargs)

def EdgeFactory(source, target):
    if channelLib.connectivityG.has_edge(source, target):
        return channelLib.connectivityG[source][target]['channel']
    elif channelLib.connectivityG.has_edge(target, source):
        return channelLib.connectivityG[target][source]['channel']
    else:
        raise ValueError('Edge {0} not found in connectivity graph'.format((
            source, target)))

