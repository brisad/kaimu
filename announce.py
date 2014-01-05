import sys
from avahiservice import AvahiAnnouncer

announcer = AvahiAnnouncer(sys.argv[1], int(sys.argv[2]))
announcer.start()
print "Announcing as", announcer.name
raw_input("Press return to stop announcing")
announcer.stop()
