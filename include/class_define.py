#! python3

import os
import re
import sys
import math
import time
import threading
import netifaces
import numpy as np

from thrift.transport import TTransport
from thrift.transport import TSocket
from thrift.protocol import TBinaryProtocol
from thrift.protocol import TMultiplexedProtocol

from bm_runtime.standard import Standard
from bm_runtime.simple_pre import SimplePre
from bm_runtime.simple_pre_lag import SimplePreLAG
from bm_runtime.standard.ttypes import BmAddEntryOptions
from bm_runtime.standard.ttypes import *
from scapy.all import *
from multiprocessing import Process, Queue, Pool

from include import runtimedata


def get_thrift_services(pre_type):
    services = [("standard", Standard.Client)]

    if pre_type == "SimplePre":
        services += [("simple_pre", SimplePre.Client)]
    elif pre_type == "SimplePreLAG":
        services += [("simple_pre_lag", SimplePreLAG.Client)]
    else:
        services += [(None, None)]

    return services


def thrift_connect(thrift_ip, thrift_port, services, out=sys.stdout):
    def my_print(s):
        out.write(s)

    # Make socket
    transport = TSocket.TSocket(thrift_ip, thrift_port)
    # Buffering is critical. Raw sockets are very slow
    transport = TTransport.TBufferedTransport(transport)
    # Wrap in a protocol
    bprotocol = TBinaryProtocol.TBinaryProtocol(transport)

    clients = []

    for service_name, service_cls in services:
        if service_name is None:
            clients.append(None)
            continue
        protocol = TMultiplexedProtocol.TMultiplexedProtocol(
            bprotocol, service_name)
        client = service_cls(protocol)
        clients.append(client)

    # Connect!
    try:
        transport.open()
    except TTransport.TTransportException:
        my_print("Could not connect to thrift client on port {}\n".format(
            thrift_port))
        my_print("Make sure the switch is running ")
        my_print("and that you have the right port\n")
        sys.exit(1)

    return clients


def MaxMinNormalization(x, Max, Min):
    if Max == Min:
        return float(x)
    x = (x - Min) / float(Max - Min)
    return x


def Z_ScoreNormalization(x, mu, sigma):
    x = (x - mu) / sigma
    return x


def sigmoid(x, useStatus):
    if useStatus:
        return 1.0 / (1 + np.exp(-float(x)))
    else:
        return float(x)


def SciKitLearn(v):
    norm = np.linalg.norm(v)
    if norm == 0:
        return v
    return v / norm


class SWITCH():
    def __init__(self, thrift_port, thrift_ip="localhost"):
        self.client = thrift_connect(thrift_ip, thrift_port,
                                     [("standard", Standard.Client)])[0]
        self.mc_client = thrift_connect(
            thrift_ip, thrift_port,
            [("simple_pre_lag", SimplePreLAG.Client)])[0]
        self.mgr_port = "s" + str(int(thrift_port) - 9000) + "-mgr"
        self.mgr_ipv6 = netifaces.ifaddresses(
            self.mgr_port)[netifaces.AF_INET6][0]['addr'].split("%")[0]
        self.mgr_mac = netifaces.ifaddresses(
            self.mgr_port)[netifaces.AF_LINK][0]['addr']
        self.name = self.mgr_port.split("-")[0]
        self.port_ipv6 = {}
        self.next_hop = {}
        self.neighbors = None
        self.index = int(self.name.split("s")[1])
        self.host_ipv6 = None

    def _description(self):
        str = "Switch %s description:\nManager_port = %s\n \
            Manager_ipv6 = %s\nManager_mac = %s\nPorts = %s\n \
            Next_hop = %s\nHost_ipv6 = %s" % (
            self.name, self.mgr_port, self.mgr_ipv6, self.mgr_mac,
            self.port_ipv6, self.next_hop, self.host_ipv6)
        print(str)

    def _port_map(self, port, port_ipv6, next_hop):
        self.port_ipv6[port] = port_ipv6
        self.next_hop[port] = next_hop
        # tmp = []
        # for port in next_hop:
        #     sw = port.split("-")[0].split("s")[1]
        #     tmp.append(int(sw))
        # self.neighbors = list(set(tmp))

    def counter_read(self, counter_name, index):
        return self.client.bm_counter_read(cxt_id=0,
                                           counter_name=counter_name,
                                           index=index)

    def counter_reset(self, counter_name):
        return self.client.bm_counter_reset_all(cxt_id=0,
                                                counter_name=counter_name)

    def register_write(self, register_name, index, value):
        return self.client.bm_register_write(0, register_name, index, value)

    def table_delete(self, table, entry_handle):
        return self.client.bm_mt_delete_entry(0, table, entry_handle)

    def register_read(self, register_name, index):
        return self.client.bm_register_read(0, register_name, index)

    def set_default_action(self, table_name, action, runtime_data,
                           runtime_data_types):
        message = self.client.bm_mt_set_default_action(
            0,
            table_name=table_name,
            action_name=action,
            action_data=runtimedata.parse_runtime_data(runtime_data,
                                                       runtime_data_types))
        return message

    def table_modify(self, table, handle, action, runtime_data,
                     runtime_data_types):
        entry_handle = self.client.bm_mt_modify_entry(
            0, table, handle, action,
            runtimedata.parse_runtime_data(runtime_data, runtime_data_types))
        return entry_handle

    # types mean "ip" or "mac" or a "integer", integer is bitwidth of a param
    def table_add_lpm(self, table, match_key, match_key_types, action,
                      runtime_data, runtime_data_types):
        entry_handle = self.client.bm_mt_add_entry(
            0, table,
            runtimedata.parse_lpm_match_key(match_key, match_key_types),
            action,
            runtimedata.parse_runtime_data(runtime_data, runtime_data_types),
            BmAddEntryOptions(priority=0))
        return entry_handle

    def table_add_exact(self, table, match_key, match_key_types, action,
                        runtime_data, runtime_data_types):
        entry_handle = self.client.bm_mt_add_entry(
            0, table, runtimedata.parse_match_key(match_key, match_key_types),
            action,
            runtimedata.parse_runtime_data(runtime_data, runtime_data_types),
            BmAddEntryOptions(priority=0))
        return entry_handle

    def table_add_ternary(self, table, match_key, match_key_types, action,
                          runtime_data, runtime_data_types, priority):
        entry_handle = self.client.bm_mt_add_entry(
            0, table,
            runtimedata.parse_ternary_match_key(match_key, match_key_types),
            action,
            runtimedata.parse_runtime_data(runtime_data, runtime_data_types),
            BmAddEntryOptions(priority=priority))
        return entry_handle

    def multicast_group_create(self, gid, rid, ports, lags):
        mgrp_hdl = self.mc_client.bm_mc_mgrp_create(0, int(gid))
        port_map_str = self.ports_to_port_map_str(ports)
        lag_map_str = self.ports_to_port_map_str(lags, description="lag")
        l1_hdl = self.mc_client.bm_mc_node_create(0, rid, port_map_str,
                                                  lag_map_str)
        message = self.mc_client.bm_mc_node_associate(0, mgrp_hdl, l1_hdl)
        return mgrp_hdl, l1_hdl, message

    def multicast_group_destroy(self, gid, mgrp_hdl, l1_hdl):
        # TODO
        self.mc_client.bm_mc_node_dissociate(0, mgrp_hdl, l1_hdl)
        self.mc_client.bm_mc_node_destroy(0, l1_hdl)
        self.mc_client.bm_mc_mgrp_destroy(0, int(gid))

    def table_get(self, table_name):
        entries = self.client.bm_mt_get_entries(0, table_name)
        return entries

    def mirroring_add(self, mirror_id, egress_port):
        self.client.mirroring_mapping_add(self, mirror_id, egress_port)

    def get_group(self, action_profile_name, grp_handle):
        group = self.client.bm_mt_act_prof_get_group(
            0, act_prof_name=action_profile_name, grp_handle=grp_handle)
        return group

    def create_group(self, action_profile_name):
        grp_handle = self.client.bm_mt_act_prof_create_group(
            0, act_prof_name=action_profile_name)
        return grp_handle

    def delete_group(self, action_profile_name, grp_handle):
        message = self.client.bm_mt_act_prof_delete_group(
            0, act_prof_name=action_profile_name, grp_handle=grp_handle)
        return message

    def add_member_to_group(self, action_profile_name, mbr_handle, grp_handle):
        message = self.client.bm_mt_act_prof_add_member_to_group(
            0, action_profile_name, mbr_handle, grp_handle)
        return message

    def act_prof_add_member(self, action_profile_name, action_name,
                            runtime_data, runtime_data_types):
        mbr_handle = self.client.bm_mt_act_prof_add_member(
            0,
            action_profile_name,
            action_name,
            action_data=runtimedata.parse_runtime_data(runtime_data,
                                                       runtime_data_types))
        return mbr_handle

    def act_prof_remove_member_from_group(self, action_profile_name,
                                          mbr_handle, grp_handle):
        message = self.client.bm_mt_act_prof_remove_member_from_group(
            0, action_profile_name, mbr_handle, grp_handle)
        return message

    def add_entry_to_group(self, table_name, match_key, match_key_types,
                           grp_handle):
        entry_handle = self.client.bm_mt_indirect_ws_add_entry(
            0,
            table_name=table_name,
            match_key=runtimedata.parse_lpm_match_key(match_key,
                                                      match_key_types),
            grp_handle=grp_handle,
            options=BmAddEntryOptions(priority=0))
        return entry_handle

    def ports_to_port_map_str(self, ports, description="port"):
        last_port_num = 0
        port_map_str = ""
        ports_int = []
        for port_num_str in ports:
            try:
                port_num = int(port_num_str)
            except:
                raise runtimedata.UIn_Error("'%s' is not a valid %s number"
                                            "" % (port_num_str, description))
            if port_num < 0:
                raise runtimedata.UIn_Error("'%s' is not a valid %s number"
                                            "" % (port_num_str, description))
            ports_int.append(port_num)
        ports_int.sort()
        for port_num in ports_int:
            if port_num == (last_port_num - 1):
                raise runtimedata.UIn_Error("Found duplicate %s number '%s'"
                                            "" % (description, port_num))
            port_map_str += "0" * (port_num - last_port_num) + "1"
            last_port_num = port_num + 1
        return port_map_str[::-1]