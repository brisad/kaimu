#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import zmq
from unittest import TestCase, main
from mock import patch, Mock, MagicMock
from mocker import MockerTestCase, expect, ANY
import serialization
from serialization import s_req, s_res
from kaimu import FileList, RemoteFiles, \
    SharedFilesPublisher, DownloadableFilesSubscriber, FileListJSONEncoder, \
    ServiceTracker, service_discovery, KaimuApp
from fileserver import FileServer, FileReader, Downloader


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


class test_FileServer(TestCase):
    def setUp(self):
        self.context = Mock()

    def assert_json_equal(self, str1, str2):
        self.assertDictEqual(json.loads(str1), json.loads(str2))

    # Test methods that generate pipe messages

    def test_add_file(self):
        """Test that add_file sends and recieves pipe messages"""

        pipe = Mock()
        pipe.recv.return_value = None

        f = FileServer(self.context, pipe=pipe)
        f.add_file('file')

        pipe.recv.assert_called_once_with()
        pipe.send.assert_called_once_with(s_req('add_file', 'file'))

    def test_add_file_collision_throws_error(self):
        pipe = Mock()
        pipe.recv.side_effect = [s_res(True), s_res(False)]

        f = FileServer(self.context, pipe=pipe)
        f.add_file('file')
        self.assertRaises(IndexError, f.add_file, 'file')

        pipe.recv.assert_called_with()
        pipe.send.assert_called_with(s_req('add_file', 'file'))
        self.assertEqual(2, pipe.recv.call_count)
        self.assertEqual(2, pipe.send.call_count)

    def test_remove_file(self):
        """Test that remove_file sends and recieves pipe messages"""

        pipe = Mock()

        f = FileServer(self.context, pipe=pipe)
        f.remove_file('file')

        pipe.recv.assert_called_once_with()
        pipe.send.assert_called_once_with(s_req('remove_file', 'file'))

    def test_get_files(self):
        """Test that get_files sends and recieves pipe messages"""

        pipe = Mock()
        pipe.recv.return_value = s_res(['file1', 'file2'])

        f = FileServer(self.context, pipe=pipe)
        result = f.get_files()
        self.assertEqual(['file1', 'file2'], result)

        pipe.send.assert_called_once_with(s_req('get_files', None))

    def test_get_bound_port(self):
        """Test that get_files sends and recieves pipe messages"""

        pipe = Mock()
        pipe.recv.return_value = s_res(6789)

        f = FileServer(self.context, pipe=pipe)
        result = f.get_bound_port()
        self.assertEqual(6789, result)

        pipe.send.assert_called_with(s_req('get_bound_port', None))
        pipe.recv.assert_called_with()

    def test_stop(self):
        pipe = Mock()

        f = FileServer(self.context, pipe=pipe)
        f.stop()

        pipe.send.assert_called_once_with('STOP')

    # Test pipe/socket creation

    def test_pipe_creation(self):
        """Test control pipe creation in thread context of caller"""

        pipe = self.context.socket.return_value

        FileServer(self.context)

        self.context.socket.assert_called_once_with(zmq.PAIR)
        pipe.bind.assert_called_once_with("inproc://fs-pipe")

    @patch('zmq.Poller')
    def test_creation_pipe_in_thread_context(self, Poller):
        """Test control pipe creation in thread's context"""

        pipe = self.context.socket.return_value

        fs = FileServer(self.context, pipe=object())
        fs.run(iterations=0, use_frontend=False)

        Poller.return_value.register.assert_called_once_with(pipe,
                                                             zmq.POLLIN)
        self.context.socket.assert_called_once_with(zmq.PAIR)
        pipe.connect.assert_called_once_with("inproc://fs-pipe")

    @patch('zmq.Poller')
    def test_creation_frontend_in_thread_context(self, Poller):
        """Test socket creation in thread's context"""

        frontend = self.context.socket.return_value

        fs = FileServer(self.context, frontend_addr="addr:1234", pipe=object())
        fs.run(iterations=0, use_thread_pipe=False)

        Poller.return_value.register.assert_called_once_with(frontend,
                                                             zmq.POLLIN)
        self.context.socket.assert_called_once_with(zmq.ROUTER)
        frontend.bind.assert_called_once_with("addr:1234")

    # Test that messages dispatch calls to certain methods

    @patch('zmq.Poller')
    def test_pipe_stop(self, Poller):

        thread_pipe = Mock()
        Poller.return_value.poll.return_value = {thread_pipe: zmq.POLLIN}

        thread_pipe.recv.side_effect = ["STOP"]

        fs = FileServer(self.context, pipe=object())
        fs.run(thread_pipe=thread_pipe, use_frontend=False)

    @patch('zmq.Poller')
    def test_frontend_message_dispatch(self, Poller):
        """Test that socket messages go to the right method"""

        frontend = Mock()
        Poller.return_value.poll.return_value = {frontend: zmq.POLLIN}

        frontend.recv.side_effect = ["id", "message"]

        fs = FileServer(self.context, pipe=object())
        fs.on_frontend_message = Mock()
        fs.run(iterations=1, frontend=frontend, use_thread_pipe=False)

        fs.on_frontend_message.assert_called_once_with("message")

    @patch('zmq.Poller')
    def test_frontend_reply(self, Poller):
        """Test that server send message on socket back to client"""

        frontend = Mock()
        Poller.return_value.poll.return_value = {frontend: zmq.POLLIN}

        frontend.recv.side_effect = ["id", "message"]

        fs = FileServer(self.context, pipe=object())
        fs.on_frontend_message = Mock(return_value="reply")
        fs.run(iterations=1, frontend=frontend, use_thread_pipe=False)

        fs.on_frontend_message.assert_called_once_with("message")
        frontend.send_multipart.assert_called_once_with(["id", "reply"])

    @patch('zmq.Poller')
    def test_pipe_method_dispatch_and_reply(self, Poller):
        """Test that pipe message calls method and sends reply"""

        thread_pipe = Mock()
        Poller.return_value.poll.return_value = {thread_pipe: zmq.POLLIN}

        thread_pipe.recv.side_effect = [s_req('pipe_abc', 'X')]

        fs = FileServer(self.context, pipe=object())
        fs.on_pipe_abc = Mock(return_value=["fine", "reply"])
        fs.run(iterations=1, thread_pipe=thread_pipe, use_frontend=False)

        fs.on_pipe_abc.assert_called_once_with('X')
        thread_pipe.send.assert_called_once_with(s_res(["fine", "reply"]))

    # Test methods dispatched from messages

    def test_on_add_file(self):
        fs = FileServer(self.context, pipe=object())
        fs.on_add_file('/file1')
        fs.on_add_file('/file2')
        self.assertTupleEqual(('/file1', '/file2'), fs.on_get_files())

    def test_on_add_file_collision(self):
        fs = FileServer(self.context, pipe=object())
        self.assertTrue(fs.on_add_file('/file1'))
        self.assertFalse(fs.on_add_file('/file1'))
        self.assertTupleEqual(('/file1',), fs.on_get_files())

    def test_on_remove_file(self):
        fs = FileServer(self.context, pipe=object())
        fs.on_add_file('/file1')
        fs.on_add_file('/file2')
        fs.on_remove_file('/file1')
        self.assertTupleEqual(('/file2',), fs.on_get_files())

    def test_on_frontend_message_file_not_found(self):
        fs = FileServer(self.context, pipe=object())
        reply = fs.on_frontend_message('{"request": "filename.txt"}')
        self.assertEqual('{"error": "file not found"}', reply)

    def test_on_frontend_message_file_transferred(self):
        """Test that a file is transferred on request"""

        filereader = Mock()
        filereader.read.return_value = {'filename': 'file.txt',
                                        'contents': 'abc'}

        fs = FileServer(self.context, pipe=object(), reader=filereader)
        fs.on_add_file('file.txt')
        reply = fs.on_frontend_message('{"request": "file.txt"}')
        self.assert_json_equal(
            '{"filename": "file.txt", "contents": "abc"}', reply)

    def test_on_get_bound_port(self):
        """Test that the port of the frontend can be retreived"""

        fs = FileServer(self.context, frontend_addr="tcp://*:1234",
                        pipe=object())
        fs.run(iterations=0, use_thread_pipe=False)
        self.assertEqual(1234, fs.on_get_bound_port())

    def test_on_get_bound_port_random(self):
        """Test that bound port is randomized if needed"""

        socket = self.context.socket.return_value

        socket.bind_to_random_port.return_value = 5566

        fs = FileServer(self.context, pipe=object())
        fs.run(iterations=0, use_thread_pipe=False)
        self.assertEqual(5566, fs.on_get_bound_port())

        socket.bind_to_random_port.assert_called_with("tcp://*")


@patch('fileserver.open', create=True)
class test_FileReader(TestCase):
    FILENAME = "file.txt"
    CONTENTS = "File contents"

    def test_read_returns_data(self, open_mock):
        open_mock.return_value = MagicMock(spec=file)
        handle = open_mock.return_value.__enter__.return_value
        handle.read.return_value = self.CONTENTS

        result = FileReader().read(self.FILENAME)

        open_mock.assert_called_once_with(self.FILENAME)
        handle.read.assert_called_once_with()
        self.assertEqual({"filename": self.FILENAME,
                          "contents": self.CONTENTS}, result)

    def test_read_open_failure(self, open_mock):
        open_mock.return_value = MagicMock(spec=file)
        open_mock.side_effect = IOError

        result = FileReader().read(self.FILENAME)

        open_mock.assert_called_once_with(self.FILENAME)
        self.assertEqual({"error": "read error"}, result)

    def test_read_read_failure(self, open_mock):
        open_mock.return_value = MagicMock(spec=file)
        handle = open_mock.return_value.__enter__.return_value
        handle.read.side_effect = IOError

        result = FileReader().read(self.FILENAME)

        handle.read.assert_called_once_with()
        self.assertEqual({"error": "read error"}, result)


class test_Downloader(TestCase):
    ENDPOINT = "endpoint"
    FILENAME = "filename"

    def setUp(self):
        self.context = Mock()
        self.socket = self.context.socket.return_value
        self.d = Downloader(self.context, self.ENDPOINT, self.FILENAME)

    def do_download(self, recv_data):
        self.socket.recv.return_value = recv_data
        success = self.d.download()
        self.context.socket.assert_called_once_with(zmq.DEALER)
        self.socket.connect.assert_called_once_with(self.ENDPOINT)
        self.socket.send.assert_called_once_with('{"request": "%s"}' %
                                                 self.FILENAME)
        self.socket.recv.assert_called_once_with()
        return success

    @patch('os.getcwd')
    def test_creation(self, getcwd):
        self.d = Downloader(self.context, "endpoint", "filename")
        self.assertEqual(getcwd.return_value, self.d.destination)
        self.assertFalse(self.d.has_downloaded)

    def test_download(self):
        success = self.do_download('{"contents": "nothing"}')
        self.assertTrue(success)
        self.assertTrue(self.d.has_downloaded)

    def test_download_error(self):
        success = self.do_download('{"error": "file not found"}')
        self.assertFalse(success)
        self.assertFalse(self.d.has_downloaded)
        self.assertEqual("file not found", self.d.failure_reason)

    def test_download_error_no_json_data(self):
        success = self.do_download({})
        self.assertFalse(success)
        self.assertFalse(self.d.has_downloaded)
        self.assertEqual("Invalid data received from server",
                         self.d.failure_reason)


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


class test_KaimuApp(TestCase):
    def setUp(self):
        UI = Mock()
        self.context = MagicMock()
        self.app = KaimuApp(self.context, UI)

    @patch('avahiservice.AvahiAnnouncer')
    @patch('avahiservice.AvahiBrowser')
    @patch('fileserver.FileServer')
    def test_start_stop(self, FileServer, AvahiBrowser, AvahiAnnouncer):

        announcer = Mock()
        AvahiAnnouncer.return_value = announcer

        browser = Mock()
        AvahiBrowser.return_value = browser

        server = Mock()
        server.get_bound_port.return_value = 9999
        FileServer.return_value = server

        self.app.run()

        # Debug publisher thread also uses the announcer
        announcer.start.assert_called_with()
        announcer.stop.assert_called_with()

        browser.start.assert_called_once_with()
        browser.stop.assert_called_once_with()

        server.start.assert_called_once_with()
        server.get_bound_port.assert_called_once_with()
        server.stop.assert_called_once_with()

    def test_add_shared_file(self):
        fileitem = {'name': 'file.txt'}
        self.app.shared_files = Mock()
        self.app.fileserver = Mock()
        self.app.publisher = Mock()

        self.app.add_shared_file(fileitem)

        self.app.shared_files.add_item.assert_called_once_with(fileitem)
        self.app.fileserver.add_file.assert_called_once_with('file.txt')
        self.app.publisher.publish_files.assert_called_once_with(
            self.app.shared_files)

    def test_remove_shared_file(self):
        fileitem = {'name': 'file.txt'}
        self.app.shared_files = Mock()
        self.app.fileserver = Mock()
        self.app.publisher = Mock()

        self.app.remove_shared_file(fileitem)

        self.app.shared_files.del_item.assert_called_once_with(fileitem)
        self.app.fileserver.remove_file.assert_called_once_with('file.txt')
        self.app.publisher.publish_files.assert_called_once_with(
            self.app.shared_files)

    @patch('fileserver.Downloader')
    def test_request_remote_file_valid(self, Downloader):
        downloader = Downloader.return_value

        self.app.addresses = {'device': '1.2.3.4'}
        self.app.remote_files = {'device': {'port': 5678}}
        success = self.app.request_remote_file('device', 'file.txt')
        self.assertTrue(success)

        Downloader.assert_called_once_with(self.context,
                                           'tcp://1.2.3.4:5678', 'file.txt')
        downloader.download.assert_called_once_with()


if __name__ == '__main__':
    main()
