#!/usr/bin/env python
# -*- coding: utf-8 -*-
# generated by wxGlade 0.6.5 on Sun Dec  8 19:15:22 2013

import os
import json
import wx
import zmq
from collections import namedtuple
from random import randrange
from time import sleep
from threading import Thread


class ServiceTracker(object):
    """Track creation and removal of other kaimu services."""

    services = namedtuple('services', ['new', 'removed'])

    def __init__(self, socket):
        self.socket = socket

    def poll(self):
        try:
            data = json.loads(self.socket.recv(zmq.DONTWAIT))
            return self.services(data[0], data[1])
        except zmq.ZMQError:
            return self.services([], [])


class Publisher(Thread):
    def __init__(self):
        super(Publisher, self).__init__()
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.bind("tcp://*:5556")

    def run(self):
        while True:
            sleep(1)
            s = json.dumps([FileItem("file %d" % x, None, x, "device %d" % x)
                            for x in range(randrange(1, 12))],
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


class FileItem(object):
    def __init__(self, name, path, size, hosting_device):
        self.name = name
        self.path = path
        self.size = size
        self.hosting_device = hosting_device


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
        else:
            return { "name": obj.name,
                     "size": obj.size,
                     "hosting_device": obj.hosting_device }


def deserialize(s):
    """Deserialize received data from subscriber to a FileList"""

    items = [FileItem(item["name"], None, item["size"], item["hosting_device"])
             for item in json.loads(s)]
    return FileList(None, items)


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
            pos = ctrl.InsertStringItem(idx, item.name)
            ctrl.SetStringItem(pos, 1, str(item.size))
            if item.hosting_device:
                ctrl.SetStringItem(pos, 2, item.hosting_device)
            ctrl.datamap[_id] = item
            ctrl.SetItemData(idx, _id)

    def _get_list_ctrl_selected_item(self, ctrl):
        return ctrl.GetNextItem(-1, wx.LIST_NEXT_ALL, wx.LIST_STATE_SELECTED)

    def OnAdd(self, event):  # wxGlade: MainFrame.<event_handler>
        """Add a file to shared files list."""

        dlg = wx.FileDialog(self, "Choose file to add", os.getcwd(),
                            "", "*.*", wx.OPEN)
        if dlg.ShowModal() == wx.ID_OK:
            item = FileItem(dlg.GetFilename(),
                            os.path.join(dlg.GetDirectory(), dlg.GetFilename()),
                            os.path.getsize(dlg.GetFilename()), None)
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
    def OnInit(self):
        self._init_zmq()
        self.publisher = SharedFilesPublisher(
            self.pubsock, lambda obj: json.dumps(obj, cls=FileListJSONEncoder))
        self.subscriber = DownloadableFilesSubscriber(self.subsock,
                                                      deserialize)

        wx.InitAllImageHandlers()
        main_frame = MainFrame(self.publisher, None, -1, "")
        self.SetTopWindow(main_frame)
        main_frame.Show()

        self.filelist = FileList(main_frame._populate_filelist)
        self.shared_files = FileList(main_frame._populate_shared)
        self.shared_files.set_items([])
        self._start_timer()
        return 1

    def OnTimer(self, event):
        files = self.subscriber.receive_files()
        if files is not None:
            self.filelist.set_items(files)

    def _init_zmq(self):
        context = zmq.Context()
        self.subsock = context.socket(zmq.SUB)
        self.subsock.connect("tcp://localhost:5556")  # The thread
        self.subsock.connect("tcp://localhost:5557")  # Ourselves
        self.subsock.setsockopt(zmq.SUBSCRIBE, "")

        self.pubsock = context.socket(zmq.PUB)
        self.pubsock.bind("tcp://*:5557")

    def _start_timer(self):
        timerid = wx.NewId()
        self.timer = wx.Timer(self, timerid)
        wx.EVT_TIMER(self, timerid, self.OnTimer)
        self.timer.Start(150, False)


# end of class MainApp

if __name__ == "__main__":
    p = Publisher()
    p.daemon = True
    p.start()

    Kaimu = MainApp(0)
    Kaimu.MainLoop()
