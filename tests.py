#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import zmq
from unittest import TestCase, main
from mocker import MockerTestCase
from kaimu import FileList, FileItem, \
    SharedFilesPublisher, DownloadableFilesSubscriber, FileListJSONEncoder


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
        item = FileItem("Filename", 1024, "device1")
        self.assertEqual("device1", item.hosting_device)

    def test_file_size(self):
        item = FileItem("Filename", 1024, "device1")
        self.assertEqual(1024, item.size)


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
        self.mocker.result(['a', 'b', 'c'])
        self.mocker.replay()

        data = json.dumps(filelist, cls=FileListJSONEncoder)
        self.assertEqual('["a", "b", "c"]', data)


if __name__ == '__main__':
    main()
