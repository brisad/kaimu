#!/usr/bin/env python
# -*- coding: utf-8 -*-
# generated by wxGlade 0.6.5 on Sun Dec  8 19:15:22 2013

import logging
import os
import platform
import json
import wx
import zmq
import uuid
import functools
from collections import namedtuple, MutableMapping
from random import randrange
from time import sleep
from threading import Thread
from contextlib import contextmanager
import avahiservice


logging.basicConfig(level=logging.INFO)

# Add disconnect method to socket if zmq version is less than 3.2.
# Disconnect is used by ServiceTracker when a service disappears and
# since the service should go away anyway we just replace this method
# with a no-op and hope for the best.

class Socket3_2(zmq.Socket):
    def disconnect(self, addr):
        logging.debug('Socket3_2.disconnect("%s"): No operation', addr)
        pass


if tuple(map(int, zmq.zmq_version().split("."))) < (3, 2, 0):
    logging.info("Using old version of ZeroMQ (%s)" % zmq.zmq_version())
    logging.info("Replacing zmq.Socket with patched class")
    zmq.core.socket.Socket = Socket3_2


class ServiceTracker(object):
    """Track creation and removal of other kaimu services."""

    services = namedtuple('services', ['new', 'removed'])

    def __init__(self, discoversock, subsock):
        self.discoversock = discoversock
        self.subsock = subsock
        self.poller = zmq.Poller()
        self.poller.register(self.discoversock, zmq.POLLIN)
        self.hosts = {}

    def _poll(self):
        """Poll for new and removed services.

        Polls the discovery socket for all its recieved data,
        aggregates it and returns it in a named tuple 'services' with
        two fields, 'new' and 'removed'.  Each of which contains a
        list of new and removed services, respectively.

        The poll timeout is zero, so if no new and/or removed services
        data is available, the corresponding fields of the named tuple
        will have empty lists.
        """

        new = []
        removed = []
        while True:
            socks = dict(self.poller.poll(0))
            if self.discoversock in socks and \
                    socks[self.discoversock] == zmq.POLLIN:
                data = json.loads(self.discoversock.recv())
                if data[0] == "N":
                    new.append(data[1:])
                elif data[0] == "R":
                    removed.append(data[1:])
            else:
                break
        return self.services(new, removed)

    def track(self):
        """Look for services and act on any changes.

        Polls the discovery socket.  If a new service has appeared,
        its name is saved and the subscriber socket will be connected
        to it.  If a service has disappeared, its name is removed and
        the subscriber socket disconnects from it.
        """

        services = self._poll()

        for name, addr, port in services.new:
            endpoint = "tcp://%s:%s" % (addr, port)
            logging.info("Connecting to new service '%s' (%s)", name, endpoint)
            self.subsock.connect(endpoint)
            self.hosts[name] = endpoint

        for name, in services.removed:
            if name in self.hosts:
                logging.info("Disconnecting from removed service '%s' (%s)",
                             name, self.hosts[name])
                self.subsock.disconnect(self.hosts[name])
                del self.hosts[name]


class Publisher(Thread):
    def __init__(self):
        super(Publisher, self).__init__()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        port = self.socket.bind_to_random_port("tcp://*")
        self.announcer = avahiservice.AvahiAnnouncer("thread", port)
        self.announcer.start()

    def run(self):
        while True:
            sleep(1)
            s = json.dumps(
                {'name': 'Thread',
                 'data': [{'name': "file %d" % x, 'path': None, 'size': x}
                          for x in range(randrange(1, 12))]},
                cls=FileListJSONEncoder)
            self.socket.send(s)


class SharedFilesPublisher(object):
    """Distribute list of shared files to the network."""

    def __init__(self, socket, serialize_func):
        self.socket = socket
        self.serialize_func = serialize_func

    def publish_files(self, filelist):
        data = self.serialize_func(filelist)
        self.socket.send(data)


class DownloadableFilesSubscriber(object):
    """Receive downloadable files from the network."""

    def __init__(self, socket, deserialize_func):
        self.socket = socket
        self.deserialize_func = deserialize_func

    def receive_files(self):
        """Receive downloadable files.

        Returns None if there is nothing to retrieve.
        """

        try:
            data = self.socket.recv(zmq.DONTWAIT)
            return self.deserialize_func(data)
        except zmq.ZMQError:
            return None


class RemoteFiles(MutableMapping):
    def __init__(self, listener):
        self.listener = listener
        self._dict = {}

    def __delitem__(self, key):
        del self._dict[key]
        self._notify()

    def __getitem__(self, key):
        return self._dict[key]

    def __setitem__(self, key, value):
        self._dict[key] = value
        self._notify()

    def __iter__(self):
        return iter(self._dict)

    def __len__(self):
        return len(self._dict)

    def _notify(self):
        if self.listener:
            self.listener(self)

    def all_files(self):
        return [[host, file_] for host, files in sorted(self._dict.iteritems())
                for file_ in files]

    def __unicode__(self):
        return unicode(self._dict)

    def __str__(self):
        return unicode(self).encode("utf-8")


class FileList(object):
    def __init__(self, listener, items=None):
        self.listener = listener
        if items is None:
            items = []
        self.items = items

    def __iter__(self):
        for item in self.items:
            yield item

    def _notify(self):
        if self.listener:
            self.listener(self)

    def set_items(self, items):
        self.items = items
        self._notify()

    def add_item(self, item):
        self.items.append(item)
        self._notify()

    def del_item(self, item):
        self.items.remove(item)
        self._notify()


class FileListJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if hasattr(obj, "items"):
            return obj.items
        return json.JSONEncoder.default(self, obj)


def serialize(data, name):
    """Serialize shared files data to be sent."""

    return json.dumps({'name': name, 'data': data}, cls=FileListJSONEncoder)

def deserialize(s):
    """Deserialize received data from subscriber."""

    return json.loads(s)


class MainFrame(wx.Frame):
    def __init__(self, publisher, *args, **kwds):
        # begin wxGlade: MainFrame.__init__
        kwds["style"] = wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)
        self.notebook = wx.Notebook(self, -1, style=0)
        self.available_files_pane = wx.Panel(self.notebook, -1)
        self.filelist_ctrl = wx.ListCtrl(self.available_files_pane, -1, style=wx.LC_REPORT | wx.SUNKEN_BORDER)
        self.shared_files_pane = wx.Panel(self.notebook, -1)
        self.add_file_btn = wx.Button(self.shared_files_pane, wx.ID_ADD, "")
        self.remove_file_btn = wx.Button(self.shared_files_pane, wx.ID_REMOVE, "")
        self.shared_files_ctrl = wx.ListCtrl(self.shared_files_pane, -1, style=wx.LC_REPORT | wx.SUNKEN_BORDER)

        self.__set_properties()
        self.__do_layout()

        self.Bind(wx.EVT_BUTTON, self.OnAdd, self.add_file_btn)
        self.Bind(wx.EVT_BUTTON, self.OnRemove, self.remove_file_btn)
        # end wxGlade

        self.publisher = publisher

    def __set_properties(self):
        # begin wxGlade: MainFrame.__set_properties
        self.SetTitle("Kaimu")
        self.SetSize((345, 223))
        # end wxGlade

    def __do_layout(self):
        # begin wxGlade: MainFrame.__do_layout
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        shared_files_sizer = wx.BoxSizer(wx.VERTICAL)
        shared_file_btn_sizer = wx.BoxSizer(wx.HORIZONTAL)
        available_files_sizer = wx.BoxSizer(wx.HORIZONTAL)
        available_files_sizer.Add(self.filelist_ctrl, 1, wx.EXPAND, 0)
        self.available_files_pane.SetSizer(available_files_sizer)
        shared_file_btn_sizer.Add(self.add_file_btn, 0, 0, 0)
        shared_file_btn_sizer.Add(self.remove_file_btn, 0, 0, 0)
        shared_files_sizer.Add(shared_file_btn_sizer, 0, wx.EXPAND, 0)
        shared_files_sizer.Add(self.shared_files_ctrl, 1, wx.EXPAND, 0)
        self.shared_files_pane.SetSizer(shared_files_sizer)
        self.notebook.AddPage(self.available_files_pane, "Available files")
        self.notebook.AddPage(self.shared_files_pane, "Shared files")
        main_sizer.Add(self.notebook, 1, wx.EXPAND, 0)
        self.SetSizer(main_sizer)
        self.Layout()
        # end wxGlade

    def _remote_files_update(self, remote_files):
        self._populate_filelist(
            [dict([('hosting_device', x[0])] + x[1].items())
             for x in remote_files.all_files()])

    def _populate_filelist(self, files):
        self._populate_list_ctrl(self.filelist_ctrl, files)

    def _populate_shared(self, files):
        self.shared_files = files
        self._populate_list_ctrl(self.shared_files_ctrl, files)

    def _populate_list_ctrl(self, ctrl, files):
        ctrl.datamap = {}
        ctrl.ClearAll()
        ctrl.InsertColumn(0, "Filename")
        ctrl.InsertColumn(1, "Size")
        ctrl.InsertColumn(2, "Device")

        for idx, item in enumerate(files):
            _id = wx.NewId()
            pos = ctrl.InsertStringItem(idx, item['name'])
            ctrl.SetStringItem(pos, 1, str(item['size']))
            if 'hosting_device' in item:
                ctrl.SetStringItem(pos, 2, item['hosting_device'])
            ctrl.datamap[_id] = item
            ctrl.SetItemData(idx, _id)

    def _get_list_ctrl_selected_item(self, ctrl):
        return ctrl.GetNextItem(-1, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)

    def OnAdd(self, event):  # wxGlade: MainFrame.<event_handler>
        """Add a file to shared files list."""

        dlg = wx.FileDialog(self, "Choose file to add", os.getcwd(),
                            "", "*.*", wx.OPEN)
        if dlg.ShowModal() == wx.ID_OK:
            name = dlg.GetFilename()
            path = os.path.join(dlg.GetDirectory(), dlg.GetFilename())
            item = {'name': name,
                    'path': path,
                    'size': os.path.getsize(path)}
            self.shared_files.add_item(item)
        dlg.Destroy()

        self.publisher.publish_files(self.shared_files)

    def OnRemove(self, event):  # wxGlade: MainFrame.<event_handler>
        index = self._get_list_ctrl_selected_item(self.shared_files_ctrl)
        if index != -1:
            _id = self.shared_files_ctrl.GetItemData(index)
            item = self.shared_files_ctrl.datamap[_id]
            self.shared_files.del_item(item)

        self.publisher.publish_files(self.shared_files)


# end of class MainFrame
class MainApp(wx.App):
    def __init__(self, context, discoversock, *args, **kwargs):
        self.context = context
        self.discoversock = discoversock
        super(MainApp, self).__init__(*args, **kwargs)

    def OnInit(self):
        self._start_publish(self.context, platform.node())
        self._start_discover(self.context, self.discoversock)

        wx.InitAllImageHandlers()
        main_frame = MainFrame(self.publisher, None, -1, "")
        self.SetTopWindow(main_frame)
        main_frame.Show()

        self.remote_files = RemoteFiles(main_frame._remote_files_update)

        self.shared_files = FileList(main_frame._populate_shared)
        self.shared_files.set_items([])
        self.publisher_tick = 0
        self._start_timer()
        return 1

    def OnTimer(self, event):
        files = self.subscriber.receive_files()
        if files is not None:
            self.remote_files[files['name']] = files['data']

        self.tracker.track()

        self.publisher_tick += 1
        if (self.publisher_tick > 20):
            self.publisher.publish_files(self.shared_files)
            self.publisher_tick = 0

    def _start_publish(self, context, name):
        """Initialize publishing of shared files."""

        # Create publisher socket
        pubsock = context.socket(zmq.PUB)
        port = pubsock.bind_to_random_port("tcp://*")
        # Announce our service
        logging.info("Starting AvahiAnnouncer")
        self.announcer = avahiservice.AvahiAnnouncer(name, port)
        self.announcer.start()
        logging.info("Announcing ourselves as '%s' on port %d",
                     self.announcer.name, port)
        # Create our interface to the publisher socket
        self.publisher = SharedFilesPublisher(
            pubsock, functools.partial(serialize, name=self.announcer.name))

    def _start_discover(self, context, discoversock):
        """Initialize discovery and subscription of services."""

        subsock = context.socket(zmq.SUB)
        subsock.setsockopt(zmq.SUBSCRIBE, "")
        self.tracker = ServiceTracker(discoversock, subsock)
        self.subscriber = DownloadableFilesSubscriber(subsock, deserialize)

    def _start_timer(self):
        timerid = wx.NewId()
        self.timer = wx.Timer(self, timerid)
        wx.EVT_TIMER(self, timerid, self.OnTimer)
        self.timer.Start(150, False)


# end of class MainApp


def ipc_name(prefix):
    return "ipc://%s-%s" % (prefix,str(uuid.uuid4())[:13])

@contextmanager
def service_discovery(context):
    """Utility context manager for starting service discovery."""

    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, "")
    addr = ipc_name("kaimubrowse")
    socket.bind(addr)
    browser = avahiservice.AvahiBrowser(context, addr)
    logging.info("Starting AvahiBrowser")
    browser.start()
    yield socket
    logging.info("Stopping AvahiBrowser")
    browser.stop()
    socket.close()

if __name__ == "__main__":
    context = zmq.Context()

    # Start service discovery already here so that it doesn't
    # interfere with wxPython.
    with service_discovery(context) as discoversock:

        p = Publisher()
        p.daemon = True
        p.start()

        Kaimu = MainApp(context, discoversock, redirect=False)
        Kaimu.MainLoop()

        # Since the Kaimu announcer is started in MainApp.OnInit, I'd
        # rather see that it would be stopped in an OnDestroy method
        # or similar, but since I haven't found any such method I do
        # it here.
        logging.info("Stopping AvahiAnnouncer")
        Kaimu.announcer.stop()
        p.announcer.stop()
