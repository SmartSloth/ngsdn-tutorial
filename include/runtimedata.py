import argparse
import cmd
from collections import Counter
import os
import sys
import struct
import json
from functools import wraps
import bmpy_utils as utils


from bm_runtime.standard import Standard
from bm_runtime.standard.ttypes import *
from bm_runtime.standard.ttypes import BmMatchParamType, BmMatchParam, BmMatchParamExact, BmMatchParamLPM, BmMatchParamTernary, BmMatchParamValid, BmMatchParamRange

try:
    from bm_runtime.simple_pre import SimplePre
except:
    pass
try:
    from bm_runtime.simple_pre_lag import SimplePreLAG
except:
    pass


def enum(type_name, *sequential, **named):
    enums = dict(list(zip(sequential, list(range(len(sequential))))), **named)
    reverse = dict((value, key) for key, value in enums.items())

    @staticmethod
    def to_str(x):
        return reverse[x]
    enums['to_str'] = to_str

    @staticmethod
    def from_str(x):
        return enums[x]

    enums['from_str'] = from_str
    return type(type_name, (), enums)


PreType = enum('PreType', 'none', 'SimplePre', 'SimplePreLAG')
MeterType = enum('MeterType', 'packets', 'bytes')
TableType = enum('TableType', 'simple', 'indirect', 'indirect_ws')
ResType = enum('ResType', 'table', 'action_prof', 'action', 'meter_array',
               'counter_array', 'register_array', 'parse_vset')

def bytes_to_string(byte_array):
    form = 'B' * len(byte_array)
    return struct.pack(form, *byte_array)


class UIn_Error(Exception):
    def __init__(self, info=""):
        self.info = info

    def __str__(self):
        return self.info


class UIn_ResourceError(UIn_Error):
    def __init__(self, res_type, name):
        self.res_type = res_type
        self.name = name

    def __str__(self):
        return "Invalid %s name (%s)" % (self.res_type, self.name)


class UIn_MatchKeyError(UIn_Error):
    def __init__(self, info=""):
        self.info = info

    def __str__(self):
        return self.info


class UIn_RuntimeDataError(UIn_Error):
    def __init__(self, info=""):
        self.info = info

    def __str__(self):
        return self.info


class CLI_FormatExploreError(Exception):
    def __init__(self):
        pass


class UIn_BadParamError(UIn_Error):
    def __init__(self, info=""):
        self.info = info

    def __str__(self):
        return self.info


class UIn_BadIPv4Error(UIn_Error):
    def __init__(self):
        pass


class UIn_BadIPv6Error(UIn_Error):
    def __init__(self):
        pass


class UIn_BadMacError(UIn_Error):
    def __init__(self):
        pass


class MatchType:
    EXACT = 0
    LPM = 1
    TERNARY = 2
    VALID = 3
    RANGE = 4

    @staticmethod
    def to_str(x):
        return {0: "exact", 1: "lpm", 2: "ternary", 3: "valid", 4: "range"}[x]

    @staticmethod
    def from_str(x):
        return {"exact": 0, "lpm": 1, "ternary": 2, "valid": 3, "range": 4}[x]


def ipv4Addr_to_bytes(addr):
    if not '.' in addr:
        raise CLI_FormatExploreError()
    s = addr.split('.')
    if len(s) != 4:
        raise UIn_BadIPv4Error()
    try:
        return [int(b) for b in s]
    except:
        raise UIn_BadIPv4Error()


def macAddr_to_bytes(addr):
    if not ':' in addr:
        raise CLI_FormatExploreError()
    s = addr.split(':')
    if len(s) != 6:
        raise UIn_BadMacError()
    try:
        return [int(b, 16) for b in s]
    except:
        raise UIn_BadMacError()


def ipv6Addr_to_bytes(addr): 
    if not ':' in addr:
        raise CLI_FormatExploreError()
    try:
        ip = IPv6Address(addr)
    except:
        raise UIn_BadIPv6Error()
    try:
        return [ord(b) for b in ip.packed]
    except:
        raise UIn_BadIPv6Error()


def int_to_bytes(i, num):
    byte_array = []
    while i > 0:
        byte_array.append(i % 256)
        i = i // 256
        num -= 1
    if num < 0:
        raise UIn_BadParamError("Parameter is too large")
    while num > 0:
        byte_array.append(0)
        num -= 1
    byte_array.reverse()
    return byte_array


def parse_param(input_str, bitwidth):
    if bitwidth == 32:
        try:
            return ipv4Addr_to_bytes(input_str)
        except CLI_FormatExploreError:
            pass
        except UIn_BadIPv4Error:
            raise UIn_BadParamError("Invalid IPv4 address")
    elif bitwidth == 48:
        try:
            return macAddr_to_bytes(input_str)
        except CLI_FormatExploreError:
            pass
        except UIn_BadMacError:
            raise UIn_BadParamError("Invalid MAC address")
    elif bitwidth == 128:
        try:
            return ipv6Addr_to_bytes(input_str)
        except CLI_FormatExploreError:
            pass
        except UIn_BadIPv6Error:
            raise UIn_BadParamError("Invalid IPv6 address")
    try:
        input_ = int(input_str, 0)
    except:
        raise UIn_BadParamError(
            "Invalid input, could not cast to integer, try in hex with 0x prefix"
        )
    try:
        return int_to_bytes(input_, (bitwidth + 7) // 8)
    except UIn_BadParamError:
        raise


def parse_runtime_data(action, params):
    def parse_param_(field, bw):
        try:
            return parse_param(field, bw)
        except UIn_BadParamError as e:
            raise UIn_RuntimeDataError(
                "Error while parsing %s - %s" % (field, e)
            )

    bitwidths = [bw for(_, bw) in action.runtime_data]
    byte_array = []
    for input_str, bitwidth in zip(params, bitwidths):
        byte_array += [bytes_to_string(parse_param_(input_str, bitwidth))]
    return byte_array


_match_types_mapping = {
    MatchType.EXACT: BmMatchParamType.EXACT,
    MatchType.LPM: BmMatchParamType.LPM,
    MatchType.TERNARY: BmMatchParamType.TERNARY,
    MatchType.VALID: BmMatchParamType.VALID,
    MatchType.RANGE: BmMatchParamType.RANGE,
}

def parse_match_key(table, key_fields):
    
    def parse_param_(field, bw):
        try:
            return parse_param(field, bw)
        except UIn_BadParamError as e:
            raise UIn_MatchKeyError(
                "Error while parsing %s - %s" % (field, e)
            )

    params = []
    match_types = [t for (_, t, _) in table.key]
    bitwidths = [bw for (_, _, bw) in table.key]
    for idx, field in enumerate(key_fields):
        param_type = _match_types_mapping[match_types[idx]]
        bw = bitwidths[idx]
        if param_type == BmMatchParamType.EXACT:
            key = bytes_to_string(parse_param_(field, bw))
            param = BmMatchParam(type=param_type,
                                 exact=BmMatchParamExact(key))
        elif param_type == BmMatchParamType.LPM:
            try:
                prefix, length = field.split("/")
            except ValueError:
                raise UIn_MatchKeyError(
                    "Invalid LPM value {}, use '/' to separate prefix "
                    "and length".format(field))
            key = bytes_to_string(parse_param_(prefix, bw))
            param = BmMatchParam(type=param_type,
                                 lpm=BmMatchParamLPM(key, int(length)))
        elif param_type == BmMatchParamType.TERNARY:
            try:
                key, mask = field.split("&&&")
            except ValueError:
                raise UIn_MatchKeyError(
                    "Invalid ternary value {}, use '&&&' to separate key and "
                    "mask".format(field))
            key = bytes_to_string(parse_param_(key, bw))
            mask = bytes_to_string(parse_param_(mask, bw))
            if len(mask) != len(key):
                raise UIn_MatchKeyError(
                    "Key and mask have different lengths in expression %s" % field
                )
            param = BmMatchParam(type=param_type,
                                 ternary=BmMatchParamTernary(key, mask))
        elif param_type == BmMatchParamType.VALID:
            key = bool(int(field))
            param = BmMatchParam(type=param_type,
                                 valid=BmMatchParamValid(key))
        elif param_type == BmMatchParamType.RANGE:
            try:
                start, end = field.split("->")
            except ValueError:
                raise UIn_MatchKeyError(
                    "Invalid range value {}, use '->' to separate range start "
                    "and range end".format(field))
            start = bytes_to_string(parse_param_(start, bw))
            end = bytes_to_string(parse_param_(end, bw))
            if len(start) != len(end):
                raise UIn_MatchKeyError(
                    "start and end have different lengths in expression %s" % field
                )
            if start > end:
                raise UIn_MatchKeyError(
                    "start is less than end in expression %s" % field
                )
            param = BmMatchParam(type=param_type,
                                 range=BmMatchParamRange(start, end))
        else:
            assert(0)
        params.append(param)
    return params



def parse_lpm_match_key(key_fields, types):
    params = []
    tmp = []
    #print "key "+ key_fields+ " type" + types
    for input_str, t in zip(key_fields, types):
        key = bytes_to_string(parse_param(input_str, t))
        tmp.append(key)
    param = BmMatchParam(type=BmMatchParamType.LPM,
                         lpm=BmMatchParamLPM(key=tmp[0],
                                             prefix_length=int(tmp[1])))
    params.append(param)
    return params
def printable_byte_str(s):
    return ":".join([format(c, "02x") for c in s])


def BmMatchParam_to_str(self):
    return BmMatchParamType._VALUES_TO_NAMES[self.type] + "-" +\
        (self.exact.to_str() if self.exact else "") +\
        (self.lpm.to_str() if self.lpm else "") +\
        (self.ternary.to_str() if self.ternary else "") +\
        (self.valid.to_str() if self.valid else "") +\
        (self.range.to_str() if self.range else "")


def BmMatchParamExact_to_str(self):
    return printable_byte_str(self.key)


def BmMatchParamLPM_to_str(self):
    return printable_byte_str(self.key) + "/" + str(self.prefix_length)


def BmMatchParamTernary_to_str(self):
    return printable_byte_str(self.key) + " &&& " + printable_byte_str(self.mask)


def BmMatchParamValid_to_str(self):
    return ""

def BmMatchParamRange_to_str(self):
    return printable_byte_str(self.start) + " -> " + printable_byte_str(self.end_)


BmMatchParam.to_str = BmMatchParam_to_str
BmMatchParamExact.to_str = BmMatchParamExact_to_str
BmMatchParamLPM.to_str = BmMatchParamLPM_to_str
BmMatchParamTernary.to_str = BmMatchParamTernary_to_str
BmMatchParamValid.to_str = BmMatchParamValid_to_str
BmMatchParamRange.to_str = BmMatchParamRange_to_str