'''
Channels is where we store information for mapping virtual (qubit) channel to
real channels.

Split from Channels.py on Jan 14, 2016.
Moved to pony ORM from atom June 1, 2018

Original Author: Colm Ryan
Modified By: Graham Rowlands

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
import datetime
import traceback
import datetime
import importlib
import inspect
from pony.orm import *
import networkx as nx

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

def copy_entity(obj):
    """Copy a pony entity instance"""
    kwargs = {a.name: getattr(obj, a.name) for a in obj._attrs_}
    kwargs.pop("id")
    kwargs.pop("classtype")
    return obj.__class__(**kwargs)

class ChannelLibrary(object):

    def __init__(self, channel_db_name=None, database_file=":memory:", channelDict={}, **kwargs):
        """Create the channel library."""

        db = Database()
        Channels.define_entities(db)
        db.bind('sqlite', filename=database_file, create_db=True)
        db.generate_mapping(create_tables=True)

        # Dirty trick: push the correct entity defs to the calling context
        for var in ["Measurement","Qubit","Edge"]:
            inspect.stack()[1][0].f_globals[var] = getattr(Channels, var)

        self.connectivityG = nx.DiGraph()
        
        # This is still somewhere legacy QGL behavior. Massage db into dict for lookup.
        self.channelDict = {}
        self.channels = []
        self.sources = []
        self.channelDatabase = None
        self.channel_db_name = channel_db_name if channel_db_name else "temp"

        self.load_most_recent()
        # config.load_config()

        # Update the global reference
        global channelLib
        channelLib = self

    def list(self):
        select((c.label, c.time, c.id) for c in Channels.ChannelDatabase).show()

    def load_by_id(self, id_num):
        obj = select(c for c in Channels.ChannelDatabase if c.id==id_num).first()
        self.load(obj)

        self.channels = list(obj.channels)
        self.sources  = list(obj.sources)
        self.channel_db_name = obj.label

    def load(self, obj):
        self.channels = list(obj.channels)
        self.sources  = list(obj.sources)
        self.channel_db_name = obj.label
        self.channelDatabase = obj

    def load_most_recent(self, name=None):
        if name is None:
            name = self.channel_db_name
        mrcd = Channels.ChannelDatabase.select(lambda d: d.label==name).order_by(desc(Channels.ChannelDatabase.time)).first()
        if mrcd:
            self.load(mrcd)

    def new(self, name):
        self.channelDatabase = None
        self.channel_db_name = name
        self.channels = []
        self.sources = []

    def save(self):
        self.save_as(self.channel_db_name)

    def save_as(self, name):
        # Get channels that are part of the currently active db, or find those that aren't yet part of a db
        chans = list(select(c for c in Channels.Channel if (c.channel_db == self.channelDatabase) or (c.channel_db is None)))
        srcs  = list(select(c for c in Channels.MicrowaveSource if (c.channel_db == self.channelDatabase) or (c.channel_db is None)))
        cd = Channels.ChannelDatabase(label=name, time=datetime.datetime.now(), channels=chans, sources=srcs)
        self.channels = chans
        self.sources = srcs
        self.channelDatabase = cd
        commit()
        self.channel_db_name = name

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

# Convenience functions for generating and linking channels
# TODO: move these to a shim layer shared by Auspex/QGL

class APS2(object):
    def __init__(self, label, address=None, delay=0.0):
        self.chan12 = Channels.PhysicalQuadratureChannel(label=f"{label}-12", instrument=label, translator="APS2Pattern")
        self.m1     = Channels.PhysicalMarkerChannel(label=f"{label}-12m1", instrument=label, translator="APS2Pattern")
        self.m2     = Channels.PhysicalMarkerChannel(label=f"{label}-12m2", instrument=label, translator="APS2Pattern")
        self.m3     = Channels.PhysicalMarkerChannel(label=f"{label}-12m3", instrument=label, translator="APS2Pattern")
        self.m4     = Channels.PhysicalMarkerChannel(label=f"{label}-12m4", instrument=label, translator="APS2Pattern")
        
        self.trigger_interval = None
        self.trigger_source   = "External"
        self.address          = address
        self.delay            = delay
        self.master           = False

class X6(object):
    def __init__(self, label, address=None):
        self.chan1 = Channels.ReceiverChannel(label=f"RecvChan-{label}-1")
        self.chan2 = Channels.ReceiverChannel(label=f"RecvChan-{label}-2")
        
        self.address          = address
        self.reference        = "external"
        self.nbr_segments     = 1
        self.nbr_round_robins = 100
        self.acquire_mode     = "digitizer"

def new_qubit(label):
    return Channels.Qubit(label=label)

def new_source(label, source_type, address, power=-30.0):
    return Channels.MicrowaveSource(label=label, source_type=source_type, address=address, power=power)

def set_control(qubit, awg, generator=None):
    qubit.phys_chan = awg.chan12
    if generator:
        qubit.phys_chan.generator = generator
    
def set_measure(qubit, awg, dig, generator=None, dig_channel=1, trig_channel=1, gate=False, gate_channel=2, trigger_length=1e-7):
    meas = Channels.Measurement(label=f"M-{qubit.label}")
    meas.phys_chan     = awg.chan12
    
    meas.trig_chan              = Channels.LogicalMarkerChannel(label=f"digTrig-{qubit.label}")
    meas.trig_chan.phys_chan    = getattr(awg, f"m{trig_channel}")
    meas.trig_chan.pulse_params = {"length": trigger_length, "shape_fun": "constant"}
    meas.receiver_chan          = getattr(dig, f"chan{dig_channel}")

    if generator:
        meas.phys_chan.generator = generator

    if gate:
        meas.gate_chan           = Channels.LogicalMarkerChannel(label=f"M-{qubit.label}-gate")
        meas.gate_chan.phys_chan = getattr(awg, f"m{gate_channel}")
        
def set_master(awg, trig_channel=2, pulse_length=1e-7):
    st = Channels.LogicalMarkerChannel(label="slave_trig")
    st.phys_chan = getattr(awg, f"m{trig_channel}")
    st.pulse_params = {"length": pulse_length, "shape_fun": "constant"}
    awg.master = True
    awg.trigger_source = "Internal"

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

