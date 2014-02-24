#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import zmq
from unittest import TestCase, main
from mocker import MockerTestCase, expect, ANY
import serialization
from serialization import s_req, s_res
from kaimu import FileList, RemoteFiles, \
    SharedFilesPublisher, DownloadableFilesSubscriber, FileListJSONEncoder, \
    ServiceTracker, service_discovery
from fileserver import FileServer, FileReader


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


class test_RemoteFiles(MockerTestCase):
    def assertNotify(self):
        listener = self.mocker.mock()
        f = RemoteFiles(listener)
        listener(f)
        self.mocker.replay()
        return f

    def test_add_item_notify(self):
        self.assertNotify()['host1'] = object()

    def test_del_item_notify(self):
        f = self.assertNotify()
        f._dict['host1'] = object()  # Avoid notification here
        del f['host1']

    def test_all_files(self):
        f = RemoteFiles(None)
        f['host1'] = {'files': ['file1', 'file2'], 'port': 0}
        f['host2'] = {'files': ['file1'], 'port': 1000}
        self.assertListEqual(
            [['host1', 'file1'], ['host1', 'file2'], ['host2', 'file1']],
            f.all_files())

    def test_str(self):
        f = RemoteFiles(None)
        f['host1'] = [1, 2, 3]
        self.assertEqual("{'host1': [1, 2, 3]}", str(f))


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


class test_ServiceTracker(MockerTestCase):
    def setUp(self):
        self.discoversock = self.mocker.mock()
        Poller = self.mocker.replace("zmq.Poller")
        self.poller = Poller()
        self.poller.register(self.discoversock, zmq.POLLIN)

    def add_poll(self, recv_data=None):
        if recv_data is None:
            expect(self.poller.poll(0)).result({})
        else:
            expect(self.poller.poll(0)).result({self.discoversock: zmq.POLLIN})
            expect(self.discoversock.recv()).result(recv_data)

    def test_poll_data(self):
        self.add_poll('["N", "hostA", "10.0.2.15", 9999]')
        self.add_poll('["R", "hostB"]')
        self.add_poll(None)
        self.mocker.replay()

        tracker = ServiceTracker(self.discoversock, None)
        services = tracker._poll()
        self.assertListEqual([["hostA", "10.0.2.15", 9999]], services.new)
        self.assertListEqual([["hostB"]], services.removed)

    def test_poll_no_data(self):
        self.add_poll(None)
        self.mocker.replay()

        tracker = ServiceTracker(self.discoversock, None)
        services = tracker._poll()
        self.assertListEqual([], services.new)
        self.assertListEqual([], services.removed)

    def test_register_poller(self):
        self.mocker.replay()
        tracker = ServiceTracker(self.discoversock, None)

    def test_track(self):
        with self.mocker.order():
            subsock = self.mocker.mock()
            self.add_poll('["N", "hostA", "192.168.0.10", 1234]')
            self.add_poll(None)
            subsock.connect("tcp://192.168.0.10:1234")
            self.add_poll('["R", "hostA"]')
            self.add_poll(None)
            subsock.disconnect("tcp://192.168.0.10:1234")
            self.mocker.replay()

        tracker = ServiceTracker(self.discoversock, subsock)
        tracker.track()
        self.assertEqual({"hostA": "tcp://192.168.0.10:1234"}, tracker.hosts)
        services = tracker.track()
        self.assertEqual({}, tracker.hosts)
        self.assertListEqual([], services.new)
        self.assertListEqual([["hostA"]], services.removed)


class test_service_discovery(MockerTestCase):
    def test_contextmanager(self):
        with self.mocker.order():
            context = self.mocker.mock()
            socket = self.mocker.mock()
            AvahiBrowser = self.mocker.replace("avahiservice.AvahiBrowser")
            expect(context.socket(zmq.SUB)).result(socket)
            socket.setsockopt(zmq.SUBSCRIBE, "")
            socket.bind(ANY)
            browser = AvahiBrowser(context, ANY)
            browser.start()
            browser.stop()
            socket.close()
            self.mocker.replay()

        with service_discovery(context) as s:
            self.assertEqual(s, socket)


class test_FileServer(MockerTestCase):
    def setUp(self):
        self.context = self.mocker.mock()
        self.Poller = self.mocker.replace("zmq.Poller")

    def add_data_to_receive(self, poller, socket, recv_data):
        expect(poller.poll(0)).result({socket: zmq.POLLIN})
        for msg in recv_data:
            expect(socket.recv()).result(msg)

    def expect_multipart_reply(self, socket, reply):
        socket.send_multipart(reply)

    def expect_reply(self, socket, reply):
        socket.send(reply)

    def assert_json_equal(self, str1, str2):
        self.assertDictEqual(json.loads(str1), json.loads(str2))

    # Test methods that generate pipe messages

    def test_add_file(self):
        """Test that add_file sends and recieves pipe messages"""

        pipe = self.mocker.mock()
        pipe.send(s_req('add_file', 'file'))
        pipe.recv()
        self.mocker.replay()

        f = FileServer(self.context, pipe=pipe)
        f.add_file('file')

    def test_add_file_collision_throws_error(self):
        pipe = self.mocker.mock()
        pipe.send(s_req('add_file', 'file'))
        pipe.send(s_req('add_file', 'file'))
        expect(pipe.recv()).result(s_res(True))
        expect(pipe.recv()).result(s_res(False))
        self.mocker.replay()

        f = FileServer(self.context, pipe=pipe)
        f.add_file('file')
        self.assertRaises(IndexError, f.add_file, 'file')

    def test_remove_file(self):
        """Test that remove_file sends and recieves pipe messages"""

        pipe = self.mocker.mock()
        pipe.send(s_req('remove_file', 'file'))
        pipe.recv()
        self.mocker.replay()

        f = FileServer(self.context, pipe=pipe)
        f.remove_file('file')

    def test_get_files(self):
        """Test that get_files sends and recieves pipe messages"""

        pipe = self.mocker.mock()
        pipe.send(s_req('get_files', None))
        expect(pipe.recv()).result(s_res(['file1', 'file2']))
        self.mocker.replay()

        f = FileServer(self.context, pipe=pipe)
        result = f.get_files()
        self.assertEqual(['file1', 'file2'], result)

    def test_stop(self):
        pipe = self.mocker.mock()
        pipe.send('STOP')
        self.mocker.replay()

        f = FileServer(self.context, pipe=pipe)
        f.stop()

    # Test pipe/socket creation

    def test_pipe_creation(self):
        """Test control pipe creation in callers thread context"""

        pipe = self.context.socket(zmq.PAIR)
        pipe.bind("inproc://fs-pipe")
        self.mocker.replay()

        FileServer(self.context)

    def test_creation_pipe_in_thread_context(self):
        """Test control pipe creation in thread's context"""

        pipe = self.mocker.mock()
        expect(self.context.socket(zmq.PAIR)).result(pipe)
        pipe.connect("inproc://fs-pipe")

        poller = self.Poller()
        poller.register(pipe, zmq.POLLIN)
        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        fs.run(iterations=0, use_frontend=False)

    def test_creation_frontend_in_thread_context(self):
        """Test socket creation in thread's context"""

        frontend = self.mocker.mock()
        expect(self.context.socket(zmq.ROUTER)).result(frontend)
        frontend.bind("frontend")

        poller = self.Poller()
        poller.register(frontend, zmq.POLLIN)
        self.mocker.replay()

        fs = FileServer(self.context, frontend_addr="frontend", pipe=object())
        fs.run(iterations=0, use_thread_pipe=False)


    # Test that messages dispatch calls to certain methods

    def test_pipe_stop(self):
        thread_pipe = self.mocker.mock()
        self.add_data_to_receive(self.Poller(), thread_pipe, ["STOP"])

        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        fs.run(thread_pipe=thread_pipe, use_frontend=False)

    def test_frontend_message_dispatch(self):
        """Test that socket messages go to the right method"""

        frontend = self.mocker.mock()

        poller = self.Poller()
        poller.register(frontend, zmq.POLLIN)
        self.add_data_to_receive(poller, frontend, ["id", "message"])
        self.expect_multipart_reply(frontend, ANY)

        on_frontend_message = self.mocker.mock()
        on_frontend_message("message")

        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        fs.on_frontend_message = on_frontend_message
        fs.run(iterations=1, frontend=frontend, use_thread_pipe=False)

    def test_frontend_reply(self):
        """Test that server send message on socket back to client"""

        frontend = self.mocker.mock()

        poller = self.Poller()
        poller.register(frontend, zmq.POLLIN)
        self.add_data_to_receive(poller, frontend, ["id", "message"])
        self.expect_multipart_reply(frontend, ["id", "reply"])

        on_frontend_message = self.mocker.mock()
        expect(on_frontend_message("message")).result("reply")

        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        fs.on_frontend_message = on_frontend_message
        fs.run(iterations=1, frontend=frontend, use_thread_pipe=False)

    def test_pipe_method_dispatch_and_reply(self):
        """Test that pipe message calls method and sends reply"""

        thread_pipe = self.mocker.mock()
        on_pipe_abc = self.mocker.mock()

        self.add_data_to_receive(self.Poller(), thread_pipe,
                                 [s_req('pipe_abc', 'X')])
        self.expect_reply(thread_pipe, s_res(["fine", "reply"]))
        expect(on_pipe_abc('X')).result(["fine", "reply"])
        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        fs.on_pipe_abc = on_pipe_abc
        fs.run(iterations=1, thread_pipe=thread_pipe, use_frontend=False)

    # Test methods dispatched from messages

    def test_on_add_file(self):
        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        fs.on_add_file('/file1')
        fs.on_add_file('/file2')
        self.assertTupleEqual(('/file1', '/file2'), fs.on_get_files())

    def test_on_add_file_collision(self):
        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        self.assertTrue(fs.on_add_file('/file1'))
        self.assertFalse(fs.on_add_file('/file1'))
        self.assertTupleEqual(('/file1',), fs.on_get_files())

    def test_on_remove_file(self):
        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        fs.on_add_file('/file1')
        fs.on_add_file('/file2')
        fs.on_remove_file('/file1')
        self.assertTupleEqual(('/file2',), fs.on_get_files())

    def test_on_frontend_message_file_not_found(self):
        self.mocker.replay()

        fs = FileServer(self.context, pipe=object())
        reply = fs.on_frontend_message('{"request": "filename.txt"}')
        self.assertEqual('{"error": "file not found"}', reply)

    def test_on_frontend_message_file_transferred(self):
        """Test that a file is transferred on request"""

        filereader = self.mocker.mock()
        expect(filereader.read('file.txt')).result(
            {'filename': 'file.txt', 'contents': 'abc'})
        self.mocker.replay()

        fs = FileServer(self.context, pipe=object(), reader=filereader)
        fs.on_add_file('file.txt')
        reply = fs.on_frontend_message('{"request": "file.txt"}')
        self.assert_json_equal(
            '{"filename": "file.txt", "contents": "abc"}', reply)


class test_FileReader(MockerTestCase):
    FILENAME = "file.txt"
    CONTENTS = "File contents"

    def setUp(self):
        self.open_func = self.mocker.mock()
        self.reader = FileReader(open_func=self.open_func)

    def test_read_open_failure(self):
        expect(self.open_func(self.FILENAME)).throw(IOError)
        self.mocker.replay()

        result = self.reader.read(self.FILENAME)
        self.assertEqual({"error": "read error"}, result)

    def test_read_read_failure(self):
        file_desc = self.open_func(self.FILENAME)
        expect(file_desc.read()).throw(IOError)
        self.mocker.replay()

        result = self.reader.read(self.FILENAME)
        self.assertEqual({"error": "read error"}, result)

    def test_read_returns_data(self):
        file_desc = self.open_func(self.FILENAME)
        expect(file_desc.read()).result(self.CONTENTS)
        self.mocker.replay()

        result = self.reader.read(self.FILENAME)
        self.assertEqual({"filename": self.FILENAME,
                          "contents": self.CONTENTS}, result)


class test_serialization(TestCase):
    def assert_json_equal(self, str1, str2):
        self.assertDictEqual(json.loads(str1), json.loads(str2))

    def test_deserialize_request(self):
        string = '{"method": "X", "params": [1, 2, 3, {"x": "y"}]}'
        expected = serialization.Request("X", [1, 2, 3, {'x': 'y'}])
        result = serialization.deserialize(string)
        self.assertEqual(expected, result)

    def test_deserialize_result(self):
        string = '{"result": [1, 2, 3, {"x": "y"}]}'
        expected = serialization.Response([1, 2, 3, {'x': 'y'}])
        result = serialization.deserialize(string)
        self.assertEqual(expected, result)

    def test_serialize_request(self):
        message = serialization.Request("Y", ['A', 'B', 'C'])
        expected = '{"method": "Y", "params": ["A", "B", "C"]}'
        string = serialization.serialize(message)

        self.assert_json_equal(expected, string)

    def test_serialize_result(self):
        message = serialization.Response([1, 2, 3])
        expected = '{"result": [1, 2, 3]}'
        string = serialization.serialize(message)
        self.assert_json_equal(expected, string)

    def test_s_req(self):
        """Test convenience method for serializing Request"""

        expected = '{"method": "Z", "params": 100}'
        result = serialization.s_req("Z", 100)
        self.assert_json_equal(expected, result)

    def test_s_res(self):
        """Test convenience method for serializing Response"""

        expected = '{"result": [1]}'
        result = serialization.s_res([1])
        self.assert_json_equal(expected, result)


if __name__ == '__main__':
    main()
