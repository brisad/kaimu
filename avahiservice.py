import uuid
from multiprocessing import Process
import zmq
import dbus
import dbus.glib
from dbus.mainloop.glib import DBusGMainLoop
import avahi
import gobject


TYPE = '_kaimu._tcp'

class AvahiBrowser(object):
    """Browse services with Avahi in a new process.

    Detects addition and removal of services on the local domain.
    When a service is added or removed, that information is written to
    the address passed to the constructor of the AvahiBrowser.

    AvahiBrowser will run the browser in a new process when start() is
    called.  This starts the glib main loop and will write data to the
    socket whenever it gets any new information.  The method stop()
    should be invoked in order to stop the browser and terminate the
    main loop.

    All sorts of funny things happened when the browser was run in a
    thread at the same time as wxPython, even when the glib thread
    initialization methods had been called.  The solution was to do
    the browsing in a separate process instead and be careful to spawn
    it before initializing the wxApp.  If it's spawned after wxPython
    starts, funny things will begin happening again.
    """

    CHECK_STOP_INTERVAL = 100

    def __init__(self, context, address):
        self.context = context  # used in the stop method
        self.address = address
        self.ctrladdr = "ipc://kaimuctrl-" + str(uuid.uuid4())[:13]

    def run(self):
        # This method runs in a new process, so create a new context
        context = zmq.Context()
        self.outsock = context.socket(zmq.PUSH)
        self.outsock.connect(self.address)

        # Socket for receiving the stop signal
        self.ctrlsock = context.socket(zmq.SUB)
        self.ctrlsock.setsockopt(zmq.SUBSCRIBE, "")
        self.ctrlsock.bind(self.ctrladdr)
        self.poller = zmq.Poller()
        self.poller.register(self.ctrlsock, zmq.POLLIN)

        self._start_browser()

        self.outsock.close()
        self.ctrlsock.close()
        # These are here to make sure zmq unlinks the ipc-pipes
        del self.poller
        del self.outsock
        del self.ctrlsock

    def start(self):
        self.proc = Process(target=self.run)
        self.proc.start()

    def stop(self):
        socket = self.context.socket(zmq.PUB)
        socket.connect(self.ctrladdr)
        # Send stop signal until process dies
        while self.proc.is_alive():
            socket.send("STOP")

    def _start_browser(self):
        bus = dbus.SystemBus(mainloop=DBusGMainLoop(set_as_default=True))
        self.server = dbus.Interface(bus.get_object(
                avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER),
                                     avahi.DBUS_INTERFACE_SERVER)

        service_browser = dbus.Interface(bus.get_object(
                avahi.DBUS_NAME,
                self.server.ServiceBrowserNew(
                    avahi.IF_UNSPEC, avahi.PROTO_UNSPEC,
                    TYPE, "", dbus.UInt32(0))),
                                         avahi.DBUS_INTERFACE_SERVICE_BROWSER)
        service_browser.connect_to_signal("ItemNew", self._item_new)
        service_browser.connect_to_signal("ItemRemove", self._item_remove)

        self.loop = gobject.MainLoop()
        gobject.timeout_add(self.CHECK_STOP_INTERVAL, self._check_stop)
        self.loop.run()

    def _check_stop(self):
        """Stop main loop if stop command received."""

        socks = dict(self.poller.poll(0))
        if self.ctrlsock in socks and socks[self.ctrlsock] == zmq.POLLIN:
            self.loop.quit()
            return False
        return True

    def _resolved_service(self, interface, protocol, name, service_type,
                          domain, host, aprotocol, address, port, txt, flags):
        self.outsock.send_json(["N", name, address, port])

    def _resolve_error(self, *args):
        print "Resolve error:", args

    def _item_remove(self, interface, protocol, name, service_type, domain,
                     flags):
        self.outsock.send_json(["R", name])

    def _item_new(self, interface, protocol, name, service_type, domain, flags):
        if flags & avahi.LOOKUP_RESULT_LOCAL:
            pass  # skip later?

        self.server.ResolveService(
            interface, protocol, name, service_type, domain,
            avahi.PROTO_UNSPEC, dbus.UInt32(0),
            reply_handler=self._resolved_service,
            error_handler=self._resolve_error)


class AvahiAnnouncer(object):
    """Announce a kaimu service with Avahi."""

    def __init__(self, name, port):
        self.name = name
        self.port = port

    def start(self):
        bus = dbus.SystemBus()
        server = dbus.Interface(
            bus.get_object(avahi.DBUS_NAME, avahi.DBUS_PATH_SERVER),
            avahi.DBUS_INTERFACE_SERVER)

        self.group = dbus.Interface(
            bus.get_object(avahi.DBUS_NAME, server.EntryGroupNew()),
            avahi.DBUS_INTERFACE_ENTRY_GROUP)

        while True:
            try:
                self.group.AddService(avahi.IF_UNSPEC, avahi.PROTO_INET,
                                      dbus.UInt32(0), self.name,
                                      TYPE, "", "", self.port, "")
            except dbus.DBusException as e:
                if 'CollisionError' in e.get_dbus_name():
                    self.name = server.GetAlternativeServiceName(self.name)
                else:
                    raise e
            else:
                break

        self.group.Commit()

    def stop(self):
        self.group.Reset()


# Remaining code is for testing browser and announcer

def _poll_and_print(poller, socket, timeout):
    while True:
        socks = dict(poller.poll(timeout))
        if socket in socks and socks[socket] == zmq.POLLIN:
            print socket.recv()
        else:
            break

if __name__ == '__main__':
    # Create context, socket and address
    context = zmq.Context()
    socket = context.socket(zmq.SUB)
    socket.setsockopt(zmq.SUBSCRIBE, "")
    addr = "ipc://kaimubrowser-" + str(uuid.uuid4())[:13]
    socket.bind(addr)

    # Start browser
    browser = AvahiBrowser(context, addr)
    browser.start()

    # Announce local service
    announcer = AvahiAnnouncer("localkaimu", 9999)
    announcer.start()

    poller = zmq.Poller()
    poller.register(socket, zmq.POLLIN)

    # Show new service announcement
    _poll_and_print(poller, socket, 1000)

    announcer.stop()

    # Show service removal
    _poll_and_print(poller, socket, 2000)

    browser.stop()
