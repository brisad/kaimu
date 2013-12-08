from unittest import TestCase, main
from mocker import MockerTestCase
from kaimu import FileList, FileItem


class test_FileList(MockerTestCase):
    def test_generator(self):
        f = FileList(None, ['file1', 'file2'])
        self.assertEqual(['file1', 'file2'], [x for x in f])

    def test_notify(self):
        listener = self.mocker.mock()
        listener(['file1', 'file2'])
        self.mocker.result("HEJ")
        self.mocker.replay()

        f = FileList(listener)
        f.set_items(['file1', 'file2'])


class test_FileItem(TestCase):
    def test_hosting_device(self):
        item = FileItem("Filename", 1024, "device1")
        self.assertEqual("device1", item.hosting_device)

    def test_file_size(self):
        item = FileItem("Filename", 1024, "device1")
        self.assertEqual(1024, item.size)


if __name__ == '__main__':
    main()
