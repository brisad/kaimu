"""This module is a wrapper around json methods for (de)serializing
two predefined objects: Request and Response.  There are intended to
be used for calls between threads.

Named tuple objects:
Request -- contains two parameters, 'method' and 'params'
Response -- contains one parameter, 'result'

Functions:
deserialize -- create Request or Response from json string
serialize -- create json string from Request or Response
s_req -- create Request from params and serialize
s_res -- create Response from params and serialize

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

def s_req(method, params):
    return serialize(Request(method, params))

def s_res(result):
    return serialize(Response(result))
