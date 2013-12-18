#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import zmq
from unittest import TestCase, main
from mocker import MockerTestCase
from kaimu import FileList, FileItem, \
    SharedFilesPublisher, DownloadableFilesSubscriber, FileListJSONEncoder, \
    ServiceTracker


class test_FileList(MockerTestCase):
    def assertNotify(self):
        listener = self.mocker.mock()
        f = FileList(listener, ['file1', 'file2'])
        listener(f)
        self.mocker.replay()
        return f

    def test_generator(self):
        f = FileList(None, ['file1', 'file2'])
        self.assertEqual(['file1', 'file2'], [x for x in f])

    def test_set_items_notify(self):
        self.assertNotify().set_items(['file1', 'file2'])

    def test_add_item_notify(self):
        self.assertNotify().add_item('item')

    def test_del_item(self):
        f = FileList(None, ['file1', 'file2'])
        f.del_item('file1')
        self.assertEqual(['file2'], [x for x in f])

    def test_del_item_notify(self):
        self.assertNotify().del_item('file1')


class test_FileItem(TestCase):
    def test_hosting_device(self):
        item = FileItem("Filename", None, 1024, "device1")
        self.assertEqual("device1", item.hosting_device)

    def test_file_size(self):
        item = FileItem("Filename", None, 1024, "device1")
        self.assertEqual(1024, item.size)

    def test_file_path(self):
        item = FileItem("Filename", "/path", 1024, "device1")
        self.assertEqual("/path", item.path)


class test_SharedFilesPublisher(MockerTestCase):
    def test_publish_files(self):
        filelist = object()

        serialize_func = self.mocker.mock()
        serialize_func(filelist)
        self.mocker.result('serialized data')

        socket = self.mocker.mock()
        socket.send('serialized data')

        self.mocker.replay()

        pub = SharedFilesPublisher(socket, serialize_func)
        pub.publish_files(filelist)


class test_DownloadableFilesSubscriber(MockerTestCase):
    def test_receive_files_available(self):
        socket = self.mocker.mock()
        socket.recv(zmq.DONTWAIT)
        self.mocker.result('serialized list')

        unserialize_func = self.mocker.mock()
        unserialize_func('serialized list')
        self.mocker.result('the list')
        self.mocker.replay()

        sub = DownloadableFilesSubscriber(socket, unserialize_func)
        filelist = sub.receive_files()

        self.assertEqual('the list', filelist)

    def test_receive_files_unavailable(self):
        socket = self.mocker.mock()
        socket.recv(zmq.DONTWAIT)
        self.mocker.throw(zmq.ZMQError)
        self.mocker.replay()

        sub = DownloadableFilesSubscriber(socket, None)
        filelist = sub.receive_files()

        self.assertEqual(None, filelist)


class test_FileListJSONEncoder(MockerTestCase):
    def test_encode_list(self):
        filelist = self.mocker.mock()
        filelist.items
        self.mocker.count(1, 2)
        self.mocker.result(['a', 'b', 'c'])
        self.mocker.replay()

        data = json.dumps(filelist, cls=FileListJSONEncoder)
        self.assertEqual('["a", "b", "c"]', data)

    def test_encode_file_item(self):
        fileitem = self.mocker.mock()
        fileitem.name
        self.mocker.result('name')
        fileitem.size
        self.mocker.result(1234)
        fileitem.hosting_device
        self.mocker.result('device1')
        self.mocker.replay()

        data = json.dumps(fileitem, cls=FileListJSONEncoder)
        self.assertIn('"name": "name"', data)
        self.assertIn('"size": 1234', data)
        self.assertIn('"hosting_device": "device1"', data)


class test_ServiceTracker(MockerTestCase):
    def test_poll_data_available(self):
        socket = self.mocker.mock()
        socket.recv(zmq.DONTWAIT)
        self.mocker.result('[[["host1", 1234], ["host2", 5678]], [["host3"]]]')
        self.mocker.replay()

        st = ServiceTracker(socket)
        services = st.poll()
        self.assertListEqual([["host1", 1234], ["host2", 5678]], services.new)
        self.assertListEqual([["host3"]], services.removed)

    def test_poll_data_unavailable(self):
        socket = self.mocker.mock()
        socket.recv(zmq.DONTWAIT)
        self.mocker.throw(zmq.ZMQError)
        self.mocker.replay()

        st = ServiceTracker(socket)
        services = st.poll()
        self.assertListEqual([], services.new)
        self.assertListEqual([], services.removed)


if __name__ == '__main__':
    main()
