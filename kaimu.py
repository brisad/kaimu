#!/usr/bin/env python
# -*- coding: utf-8 -*-
# generated by wxGlade 0.6.5 on Sun Dec  8 19:15:22 2013

import logging
import os
import platform
import json
import wx
from wx.lib.agw import ultimatelistctrl as ULC
import zmq
import uuid
import functools
from collections import namedtuple, MutableMapping
from contextlib import contextmanager
import fileserver

try:
    import avahiservice as zeroconf
except ImportError:
    import bonjourservice as zeroconf


if __name__ == '__main__':
    logging.basicConfig(format="[%(asctime)s] %(levelname)s:%(message)s",
                        level=logging.INFO)

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

        return services


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
        return [[host, file_] for host, data in sorted(self._dict.iteritems())
                for file_ in data['files']]

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


def serialize(files, name, port):
    """Serialize shared files data to be sent."""

    return json.dumps({'name': name, 'files': files, 'port': port},
                      cls=FileListJSONEncoder)

def deserialize(s):
    """Deserialize received data from subscriber."""

    return json.loads(s)


class MainFrame(wx.Frame):
    def __init__(self, kaimu_app, *args, **kwds):
        # begin wxGlade: MainFrame.__init__
        kwds["style"] = wx.DEFAULT_FRAME_STYLE
        wx.Frame.__init__(self, *args, **kwds)
        self.notebook = wx.Notebook(self, -1, style=0)
        self.available_files_pane = wx.Panel(self.notebook, -1)
        self.filelist_ctrl = ULC.UltimateListCtrl(self.available_files_pane, -1, agwStyle=ULC.ULC_REPORT | ULC.ULC_HAS_VARIABLE_ROW_HEIGHT)
        self.shared_files_pane = wx.Panel(self.notebook, -1)
        self.add_file_btn = wx.Button(self.shared_files_pane, wx.ID_ADD, "")
        self.remove_file_btn = wx.Button(self.shared_files_pane, wx.ID_REMOVE, "")
        self.shared_files_ctrl = ULC.UltimateListCtrl(self.shared_files_pane, -1, agwStyle=ULC.ULC_REPORT | ULC.ULC_HAS_VARIABLE_ROW_HEIGHT)

        self.__set_properties()
        self.__do_layout()

        self.Bind(wx.EVT_BUTTON, self.OnAdd, self.add_file_btn)
        self.Bind(wx.EVT_BUTTON, self.OnRemove, self.remove_file_btn)
        self.Bind(wx.EVT_NOTEBOOK_PAGE_CHANGED, self.OnPageChange, self.notebook)
        # end wxGlade

        self.filelist_ctrl.datamap = {}
        self.filelist_ctrl.InsertColumn(0, "Filename")
        self.filelist_ctrl.InsertColumn(1, "Size", wx.LIST_FORMAT_RIGHT)
        self.filelist_ctrl.InsertColumn(2, "Device")
        self.filelist_ctrl.InsertColumn(3, "Action")
        self.filelist_ctrl.SetColumnWidth(0, 164)
        self.filelist_ctrl.SetColumnWidth(1, 70)
        self.filelist_ctrl.SetColumnWidth(2, 140)

        self.shared_files_ctrl.datamap = {}
        self.shared_files_ctrl.InsertColumn(0, "Filename")
        self.shared_files_ctrl.SetColumnWidth(0, 164)
        self.shared_files_ctrl.InsertColumn(1, "Size")

        self.kaimu_app = kaimu_app

    def __set_properties(self):
        # begin wxGlade: MainFrame.__set_properties
        self.SetTitle("Kaimu")
        self.SetSize((456, 230))
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

    def _get_list_changes(self, ctrl, items):
        # Find the differences between the data items bound to the
        # ctrl and the passed items list.  Return a tuple: added,
        # unchanged, removed.  Interpret the passed items list as the
        # new state of ctrl.  Each item in unchanged and removed
        # contains extra information on where it was found in the
        # ctrl.

        # Remove items from this as we find them in the control
        added = items[:]
        unchanged = []
        removed = []
        for _id, item in ctrl.datamap.items():
            if item in items:
                # Item is present in control, unchanged
                unchanged.append((item, _id))
                del added[added.index(item)]
            else:
                # Item is present in control but not in our passed
                # data list, this has been removed
                removed.append((item, _id))
        return added, unchanged, removed

    def _remove_list_item(self, ctrl, _id):
        # Remove the list item identified by _id from ctrl
        for idx in range(ctrl.GetItemCount()):
            if ctrl.GetItemData(idx) == _id:
                ctrl.DeleteItem(idx)
                del ctrl.datamap[_id]
                return

    def _populate_filelist(self, files):
        # Populate filelist control with the list of files in files
        ctrl = self.filelist_ctrl
        added, __, removed = self._get_list_changes(ctrl, files)

        # Remove items from list control
        for __, _id in removed:
            self._remove_list_item(ctrl, _id)

        # Add new items to list control
        for item in added:
            _id = wx.NewId()
            pos = ctrl.InsertStringItem(0, item['name'])
            ctrl.SetStringItem(pos, 1, str(item['size']))
            ctrl.SetStringItem(pos, 2, item['hosting_device'])
            download_button = wx.Button(ctrl, -1, label='Download')
            ctrl.SetItemWindow(pos, 3, download_button, expand=True)

            # Attach handler to download button
            download_button.Bind(wx.EVT_BUTTON,
                                 lambda _: self._request_file(item))
            ctrl.datamap[_id] = item
            ctrl.SetItemData(0, _id)

        # Unless we do this ULC will draw its items too close to each
        # other.
        ctrl.Update()

    def _populate_shared(self, files):
        # Populate shared files control with the list of files in
        # files
        ctrl = self.shared_files_ctrl
        added, __, removed = self._get_list_changes(ctrl, list(files))

        # Remove items from list control
        for __, _id in removed:
            self._remove_list_item(ctrl, _id)

        # Add new items to list control
        for item in added:
            _id = wx.NewId()
            pos = ctrl.InsertStringItem(0, item['name'])
            ctrl.SetStringItem(pos, 1, str(item['size']))
            ctrl.datamap[_id] = item
            ctrl.SetItemData(0, _id)

    def _request_file(self, file_):
        # Ask kaimu to retrieve the given file from remote device
        success = self.kaimu_app.request_remote_file(
            file_['hosting_device'], file_['name'],
            self.OnFileRequestSuccess, self.OnFileRequestFailure)

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
            self.kaimu_app.add_shared_file(item)
        dlg.Destroy()

    def OnRemove(self, event):  # wxGlade: MainFrame.<event_handler>
        index = self._get_list_ctrl_selected_item(self.shared_files_ctrl)
        if index != -1:
            _id = self.shared_files_ctrl.GetItemData(index)
            item = self.shared_files_ctrl.datamap[_id]
            self.kaimu_app.remove_shared_file(item)

    def OnPageChange(self, event):  # wxGlade: MainFrame.<event_handler>
        # In Windows this is needed to get a correct layout of the
        # list items
        self.filelist_ctrl.Refresh()
        self.filelist_ctrl.Update()

    def OnFileRequestSuccess(self, path):
        wx.CallAfter(wx.MessageBox, "File downloaded to %s" % path)

    def OnFileRequestFailure(self, reason):
        wx.CallAfter(wx.MessageBox, "File download failed: %s" % reason)


# end of class MainFrame
class MainApp(wx.App):
    def __init__(self, kaimu_app, *args, **kwargs):
        self.kaimu_app = kaimu_app
        super(MainApp, self).__init__(*args, redirect=False, **kwargs)

    def OnInit(self):
        wx.InitAllImageHandlers()
        main_frame = MainFrame(self.kaimu_app, None, -1, "")
        self.SetTopWindow(main_frame)
        main_frame.Show()

        self._start_timer()
        self.main_frame = main_frame
        return 1

    def OnTimer(self, event):
        self.kaimu_app.timer_event()

    def _start_timer(self):
        timerid = wx.NewId()
        self.timer = wx.Timer(self, timerid)
        wx.EVT_TIMER(self, timerid, self.OnTimer)
        self.timer.Start(150, False)

    def on_shared_files_update(self, files):
        self.main_frame._populate_shared(files)

    def on_remote_files_update(self, files):
        self.main_frame._remote_files_update(files)


# end of class MainApp


@contextmanager
def service_discovery(context):
    """Utility context manager for starting service discovery."""

    browser = zeroconf.Browser(context)
    logging.info("Starting browser")
    browser.start()
    yield browser.socket
    logging.info("Stopping browser")
    browser.stop()


class KaimuApp(object):
    def __init__(self, context, UI):
        self.context = context
        self.UI = UI
        self.addresses = {}
        self.publisher_tick = 0

    def run(self):
        with service_discovery(self.context) as discoversock:
            self.shared_files = FileList(None)
            self.remote_files = RemoteFiles(None)

            self.fileserver = fileserver.FileServer(self.context)
            self.fileserver.start()
            fileserver_port = self.fileserver.get_bound_port()
            logging.info("File server running on port %d" % fileserver_port)
            self._start_publish(self.context, platform.node(), fileserver_port)
            self._start_discover(self.context, discoversock)

            UI = self.UI(self)

            self.shared_files.listener = UI.on_shared_files_update
            self.remote_files.listener = UI.on_remote_files_update

            UI.MainLoop()

            self.fileserver.stop()

            logging.info("Stopping announcer")
            self.announcer.stop()

    def _start_publish(self, context, name, server_port):
        """Initialize publishing of shared files."""

        # Create publisher socket
        pubsock = context.socket(zmq.PUB)
        port = pubsock.bind_to_random_port("tcp://*")
        # Announce our service
        logging.info("Starting announcer")
        self.announcer = zeroconf.Announcer(name, port)
        self.announcer.start()
        logging.info("Announcing ourselves as '%s' on port %d",
                     self.announcer.name, port)
        # Create our interface to the publisher socket
        self.publisher = SharedFilesPublisher(
            pubsock, functools.partial(serialize, name=self.announcer.name,
                                       port=server_port))

    def _start_discover(self, context, discoversock):
        """Initialize discovery and subscription of services."""

        subsock = context.socket(zmq.SUB)
        subsock.setsockopt(zmq.SUBSCRIBE, "")
        self.tracker = ServiceTracker(discoversock, subsock)
        self.subscriber = DownloadableFilesSubscriber(subsock, deserialize)

    def timer_event(self):
        services = self.tracker.track()

        for name, addr, port in services.new:
            self.addresses[name] = addr

        for removed, in services.removed:
            # If we have a list of files from a removed service, clear
            # it since it is no longer available
            if removed in self.remote_files:
                logging.debug('Removing list of files belonging to %s', removed)
                del self.remote_files[removed]
            else:
                logging.debug("Didn't have any files belonging to %s", removed)

        files = self.subscriber.receive_files()
        if files is not None:
            name = files['name']
            contents = {k: files[k] for k in ('files', 'port')}
            if self.remote_files.get(name) != contents:
                self.remote_files[name] = contents

        self.publisher_tick += 1
        if (self.publisher_tick > 20):
            self.publisher.publish_files(self.shared_files)
            self.publisher_tick = 0

    def add_shared_file(self, fileitem):
        """Add file to list of shared files

        fileitem is expected to be a dictionary containing the fields
        name, path, and size.
        """

        try:
            self.fileserver.add_file(fileitem['path'])
        except IndexError:
            pass
        else:
            self.shared_files.add_item(fileitem)
            self.publisher.publish_files(self.shared_files)

    def remove_shared_file(self, fileitem):
        """Remove file from list of shared files

        fileitem has to be equal to an object previously added with
        add_shared_file.
        """

        self.shared_files.del_item(fileitem)
        self.fileserver.remove_file(fileitem['path'])
        self.publisher.publish_files(self.shared_files)

    def _remote_file_callback(self, status, on_success, on_failure):
        if status['success']:
            on_success(status['path'])
        else:
            on_failure(status['reason'])

    def request_remote_file(self, device, filename, on_success, on_failure):
        logging.info("Request remote file '%s' from '%s'" % (filename, device))
        endpoint = "tcp://%s:%d" % (self.addresses[device],
                                    self.remote_files[device]['port'])
        downloader = fileserver.Downloader(self.context, endpoint, filename)

        logging.info("Starting download from %s" % endpoint)

        downloader.download(functools.partial(
                self._remote_file_callback,
                on_success=on_success, on_failure=on_failure))


if __name__ == '__main__':
    KaimuApp(zmq.Context(), MainApp).run()
