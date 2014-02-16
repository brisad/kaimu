"""This module is a wrapper around json methods for (de)serializing
two predefined objects: Request and Response.  There are intended to
be used for calls between threads.

Named tuple objects:
Request -- contains two parameters, 'method' and 'params'
Response -- contains one parameter, 'result'

Functions:
deserialize -- create Request or Response from json string
serialize -- create json string from Request or Response

"""

import json
from collections import namedtuple


Request = namedtuple('Request', ['method', 'params'])
Response = namedtuple('Response', ['result'])

def deserialize(serialized_message):
    message = json.loads(serialized_message)
    if 'result' in message:
        return Response(message['result'])
    else:
        return Request(message['method'], message['params'])

def serialize(message):
    return json.dumps(dict(message.__dict__))
