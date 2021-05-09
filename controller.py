import os
import re
import sys
import math
import time
import random
import pickle
import threading
import traceback
import netifaces
import subprocess
import networkx as nx
import matplotlib.pyplot as plt

import include.runtimedata
from include.class_define import SWITCH, thrift_connect

# links = [["eth0:s1-eth1", "eth1:s2-eth1"], ["eth0:s1-host"], ["eth0:s2-host"]]


class Controller():
    def __init__(self):
        self.SWITCH_NUM = 0
        self.TOPO_FILE = "/int/topo/default_topo"
        self.GRAPH = nx.Graph()
        self.LINK_LIST = self.readTopoFile()
        self.SWITCH_LIST = self.switchConnect()
        self.DOWNSTREAM_GROUP_HANDLE = {}
        self.UPSTREAM_GROUP_HANDLE = {}
        self.DOWNSTREAM_MEMBER_HANDLE = {}
        self.UPSTREAM_MEMBER_HANDLE = {}
        self.PORT_IPV6 = {}

    def switchConnect(self):
        try:
            self.SWITCH_NUM = int(
                os.popen("netstat -tunlp | grep simple_switch | wc -l").
                readlines()[0])
            print("Now has %d switches" % self.SWITCH_NUM)
            switch_list = []
            for index in range(self.SWITCH_NUM):
                sw = SWITCH(9000 + index, "127.0.0.1")
                # print("has ports %s" % (self.LINK_LIST[str(index)].keys()))
                for port in self.LINK_LIST[str(index)].keys():
                    ipv6 = netifaces.ifaddresses(port)[
                        netifaces.AF_INET6][0]['addr']
                    ipv6 = ipv6.split("%")[0]
                    sw._port_map(port, ipv6, self.LINK_LIST[str(index)][port])
                switch_list.append(sw)
        except:
            print("connect error")
        return switch_list

    def readTopoFile(self):
        with open(self.TOPO_FILE, "r") as f:
            cmds = f.readlines()
        tors = cmds[:2][0][:-1].split(":")[-1]
        core = cmds[:2][1][:-1].split(":")[-1]
        tors = [_[1:] for _ in tors.split(",")]
        core = [_[1:] for _ in core.split(",")]
        sws = tors + core
        # print(sws)
        nodes = [str("s" + str(i)) for i in sws]
        color_map = {}
        for sw in sws:
            s_name = "s" + str(sw)
            if sw in tors:
                color_map[s_name] = 'red'
            else:
                color_map[s_name] = 'green'
        self.GRAPH.add_nodes_from(nodes)
        colors = [color_map.get(node, 0.25) for node in self.GRAPH.nodes()]
        # print("color_map has %s" % color_map)
        # print("colors has %s" % colors)

        links = dict(zip(sws, [{} for _ in sws]))
        topo = cmds[2:]
        edges = []
        for t in topo:
            s1 = t[:-1].split("-")[0]
            s2 = t[:-1].split("-")[1]
            edges.append((s1.split(":")[0], s2.split(":")[0]))
            s1_name = s1.split(":")[0][1:]
            s1_iface = s1.split(":")[1]
            s2_name = s2.split(":")[0][1:]
            s2_iface = s2.split(":")[1]
            s1_point = "s%s-eth%s" % (s1_name, s1_iface)
            s2_point = "s%s-eth%s" % (s2_name, s2_iface)
            links[s1_name][s1_point] = s2_point
            links[s2_name][s2_point] = s1_point
        self.GRAPH.add_edges_from(edges)
        nx.draw(
            self.GRAPH,
            # cmap=plt.get_cmap('viridis'),
            with_labels=True,
            node_color=colors,
            font_color='white',
        )
        plt.savefig("topo_graph.png")
        plt.show()
        return links

    # IngressPipeImpl.ndp_reply_table(hdr.ndp.target_ipv6_addr)
    def writeNdpReply(self, switch, targetIpv6Addr, targetMac):
        info = switch.table_add_exact(table="IngressPipeImpl.ndp_reply_table",
                                      match_key=[str(targetIpv6Addr)],
                                      match_key_types=['ipv6'],
                                      action="IngressPipeImpl.ndp_ns_to_na",
                                      runtime_data=[str(targetMac)],
                                      runtime_data_types=['mac'])
        print("Insert ndp_reply_table on %s successfully: %s" %
              (switch.name, info))
        return info

    # IngressPipeImpl.my_station_table(hdr.ethernet.dst_addr)
    # only a counter counting how many l2 packet reach here
    # same as rmac.hit()
    def writeMyStationTable(self, switch, ethDstAddr):
        info = switch.table_add_exact(table="IngressPipeImpl.my_station_table",
                                      match_key=[str(ethDstAddr)],
                                      match_key_types=['mac'],
                                      action="NoAction",
                                      runtime_data=[],
                                      runtime_data_types=[])
        print("Insert my_station_table on %s successfully: %s" %
              (switch.name, info))
        return info

    # IngressPipeImpl.srv6_my_sid(hdr.ipv6.dst_addr)
    def writeSRv6MySidTable(self, switch, localIpv6Addr):
        info = switch.table_add_lpm(table="IngressPipeImpl.srv6_my_sid",
                                    match_key=[str(localIpv6Addr), '128'],
                                    match_key_types=['ipv6', '32'],
                                    action="IngressPipeImpl.srv6_end",
                                    runtime_data=[],
                                    runtime_data_types=[])
        print("Insert srv6_my_sid on %s successfully: %s" %
              (switch.name, info))
        return info

    # IngressPipeImpl.srv6_transit(hdr.ipv6.dst_addr)
    def writeSRv6TransitTable(self, switch, dstIpv6Addr, prefixLength,
                              segmentList):
        info = switch.table_add_lpm(
            table="IngressPipeImpl.srv6_transit",
            match_key=[str(dstIpv6Addr), str(prefixLength)],
            match_key_types=['ipv6', '32'],
            action="IngressPipeImpl.srv6_t_insert_2",
            runtime_data=segmentList,
            runtime_data_types=['ipv6', 'ipv6'])
        print("Insert srv6_transit on %s successfully: %s" %
              (switch.name, info))
        return info

    # IngressPipeImpl.l2_exact_table(hdr.ethernet.dst_addr)
    def writeL2ExactTable(self, switch, ethDstAddr, egressPort):
        info = switch.table_add_exact(table="IngressPipeImpl.l2_exact_table",
                                      match_key=[str(ethDstAddr)],
                                      match_key_types=['mac'],
                                      action="IngressPipeImpl.set_egress_port",
                                      runtime_data=[str(egressPort)],
                                      runtime_data_types=['9'])
        print("Insert l2_exact_table on %s successfully: %s" %
              (switch.name, info))
        return info

    # IngressPipeImpl.l2_ternary_table(hdr.ethernet.dst_addr)
    # TODO: no need temporaryly
    def writeL2TernaryTable(self, switch, ethDstAddr, multicastGroup):
        info = switch.table_add_lpm(
            table="IngressPipeImpl.l2_ternary_table",
            match_key=[str(ethDstAddr)],
            match_key_types=['mac'],
            action="IngressPipeImpl.set_multicast_group",
            runtime_data=[str(multicastGroup)],
            runtime_data_types=[''])
        print("Insert l2_ternary_table on %s successfully: %s" %
              (switch.name, info))
        return info

    # IngressPipeImpl.acl_table(standard_metadata.ingress_port)
    def writeAclTable(self, switch, ingressPort, ethDstAddr, ethSrcAddr,
                      ethType, ipProto, icmpType, l4DstPort, l4SrcPort):
        info = switch.table_add_ternary(
            table="IngressPipeImpl.acl_table",
            match_key=[
                str(ingressPort),
                str(ethDstAddr),
                str(ethSrcAddr),
                str(ethType),
                str(ipProto),
                str(icmpType),
                str(l4DstPort),
                str(l4SrcPort)
            ],
            match_key_types=['9', 'mac', 'mac', '16', '8', '8', '16', '16'],
            action="IngressPipeImpl.send_to_cpu",
            runtime_data=[],
            runtime_data_types=[])
        print("Insert acl_table on %s successfully: %s" % (switch.name, info))
        return info

    # IngressPipeImpl.routing_v6_table(hdr.ipv6.dst_addr)
    def writeRoutingIpv6Table(self, switch, dstIpv6Addr, nextHopMac):
        info = switch.table_add_lpm(table="IngressPipeImpl.routing_v6_table",
                                    match_key=[str(dstIpv6Addr), 128],
                                    match_key_types=['ipv6', '32'],
                                    action="IngressPipeImpl.set_next_hop",
                                    runtime_data=[str(nextHopMac)],
                                    runtime_data_types=['mac'])
        print("Insert routing_v6_table on %s successfully: %s" %
              (switch.name, info))
        return info

    def writeEcmpGroupRoutingTable(self, switch, dstIpv6Addr, grp_handle):
        info = switch.add_entry_to_group(
            table_name="IngressPipeImpl.routing_v6_table",
            match_key=[dstIpv6Addr, 128],
            match_key_types=["ipv6", "32"],
            grp_handle=grp_handle)
        print("Insert routing_v6_table on %s successfully: %s" %
              (switch.name, info))
        return info

    def createEcmpSelectorGroup(self, switch, downstreamGroupSwitches,
                                upstreamGroupSwitches):
        if len(downstreamGroupSwitches) > 0:
            downstream_grp_handle = switch.create_group(
                "IngressPipeImpl.ecmp_selector")
            self.DOWNSTREAM_GROUP_HANDLE[str(
                switch.name)] = downstream_grp_handle
            print(
                "Create ecmp_selector group on %s successfully: downstream group is %s"
                % (switch.name, downstream_grp_handle))
            # add downstream switches to member
            for i in range(len(downstreamGroupSwitches)):
                info = switch.act_prof_add_member(
                    action_profile_name="IngressPipeImpl.ecmp_selector",
                    action_name="IngressPipeImpl.set_next_hop",
                    runtime_data=[str(downstreamGroupSwitches[i].mgr_mac)],
                    runtime_data_types=['mac'])
                self.DOWNSTREAM_MEMBER_HANDLE[str(switch.name)] = info
                print(
                    "Add switch %s to downstream group on %s successfully: %s"
                    % (downstreamGroupSwitches[i].name, switch.name, info))
                switch.add_member_to_group(
                    action_profile_name="IngressPipeImpl.ecmp_selector",
                    mbr_handle=self.DOWNSTREAM_MEMBER_HANDLE[str(switch.name)],
                    grp_handle=self.DOWNSTREAM_GROUP_HANDLE[str(switch.name)])

        if len(upstreamGroupSwitches) > 0:
            upstream_grp_handle = switch.create_group(
                "IngressPipeImpl.ecmp_selector")
            self.UPSTREAM_GROUP_HANDLE[str(switch.name)] = upstream_grp_handle
            print(
                "Create ecmp_selector group on %s successfully: upstream is %s"
                % (switch.name, upstream_grp_handle))
            # add upstream switches to member
            for i in range(len(upstreamGroupSwitches)):
                info = switch.act_prof_add_member(
                    action_profile_name="IngressPipeImpl.ecmp_selector",
                    action_name="IngressPipeImpl.set_next_hop",
                    runtime_data=[str(upstreamGroupSwitches[i].mgr_mac)],
                    runtime_data_types=['mac'])
                self.UPSTREAM_MEMBER_HANDLE[str(switch.name)] = info
                print(
                    "Add switch %s to upstream group on %s successfully: %s" %
                    (upstreamGroupSwitches[i].name, switch.name, info))
                switch.add_member_to_group(
                    action_profile_name="IngressPipeImpl.ecmp_selector",
                    mbr_handle=self.UPSTREAM_MEMBER_HANDLE[str(switch.name)],
                    grp_handle=self.UPSTREAM_GROUP_HANDLE[str(switch.name)])

    def deleteAllEntries(self):
        for sw in self.SWITCH_LIST:
            for table in [
                    "IngressPipeImpl.ndp_reply_table",
                    "IngressPipeImpl.my_station_table",
                    "IngressPipeImpl.srv6_my_sid",
                    "IngressPipeImpl.srv6_transit",
                    "IngressPipeImpl.l2_exact_table",
                    "IngressPipeImpl.l2_ternary_table",
                    "IngressPipeImpl.acl_table",
                    "IngressPipeImpl.routing_v6_table"
            ]:
                entries = sw.table_get(table)
                for e in entries:
                    entry_handle = self.getEntryHandle(str(e))
                    sw.table_delete(table, entry_handle)

    def deleteGroups(self, switch):
        if switch in self.GROUP_HANDLE.keys():
            switch.delete_group("IngressPipeImpl.ecmp_selector",
                                self.GROUP_HANDLE[str(switch.name)])
        self.GROUP_HANDLE.pop(switch.name)
        print("Delete all groups in %s successfully." % switch.name)

    def deleteEntries(self, switch, entry_hdl_map):
        for table in entry_hdl_map.keys():
            if len(entry_hdl_map.get(table)) == 0:
                continue
            for entry_handle in entry_hdl_map.get(table):
                try:
                    switch.table_delete(table, entry_handle)
                except Exception as e:
                    raise ("Delete %s to %s failed, with error %s and traceback %s" % \
                        (table, switch.name, e, traceback.format_exc()))
        print("Delete all entries in %s successfully." % switch.name)

    def insertAllEntries(self):
        for sw in self.SWITCH_LIST:
            entry_hdl_map = {
                "IngressPipeImpl.ndp_reply_table": [],
                "IngressPipeImpl.my_station_table": [],
                "IngressPipeImpl.srv6_my_sid": [],
                "IngressPipeImpl.srv6_transit": [],
                "IngressPipeImpl.l2_exact_table": [],
                "IngressPipeImpl.l2_ternary_table": [],
                "IngressPipeImpl.acl_table": [],
                "IngressPipeImpl.routing_v6_table": []
            }

            for port in sw.next_hop.keys():
                nethop_mac = self.getMacByPortName(
                    self.getSwitchMgrFromPort(sw.next_hop[port]))
                # print("nexthop is %s, nethop_mac is %s, egress port is %s" % (self.getDeviceFromPort(sw.next_hop[port]), nethop_mac, port.split("eth")[1]))
                entry_hdl = self.writeL2ExactTable(sw, nethop_mac,
                                                   port.split("eth")[1])
                entry_hdl_map["IngressPipeImpl.l2_exact_table"].append(
                    entry_hdl)

            entry_hdl = self.writeNdpReply(sw, sw.mgr_ipv6, sw.mgr_mac)
            entry_hdl_map["IngressPipeImpl.ndp_reply_table"].append(entry_hdl)

            entry_hdl = self.writeSRv6MySidTable(sw, sw.mgr_ipv6)
            entry_hdl_map["IngressPipeImpl.srv6_my_sid"].append(entry_hdl)

            entry_hdl = self.writeMyStationTable(sw, sw.mgr_mac)
            entry_hdl_map["IngressPipeImpl.my_station_table"].append(entry_hdl)

            self.deleteEntries(sw, entry_hdl_map)

            upstream_ecmp_group = []
            downstream_ecmp_group = []
            print("%s nexthop has: %s" % (sw.name, sw.next_hop))
            for sw_next in sw.next_hop:
                next_hop_index = int(
                    self.switchNameToIndex(sw.next_hop[sw_next].split("-")[0]))
                if int(self.switchNameToIndex(sw.name)) < next_hop_index:
                    upstream_ecmp_group.append(
                        self.getSwitchInstanceFromPort(sw.next_hop[sw_next]))
                elif int(self.switchNameToIndex(sw.name)) > next_hop_index:
                    downstream_ecmp_group.append(
                        self.getSwitchInstanceFromPort(sw.next_hop[sw_next]))
            if len(upstream_ecmp_group) > 0 or len(downstream_ecmp_group) > 0:
                self.createEcmpSelectorGroup(sw, downstream_ecmp_group,
                                             upstream_ecmp_group)
                # print("group_handle has %s" % self.GROUP_HANDLE)
                if len(upstream_ecmp_group) > 0:
                    for dst_index in range(
                            int(sw.name.split("s")[1]) + 1,
                            int(self.SWITCH_NUM)):
                        if str("s" +
                               str(dst_index)) in self.nexthopToNeighbors(sw):
                            continue
                        else:
                            entry_hdl = self.writeEcmpGroupRoutingTable(
                                sw,
                                self.getSwitchInstanceFromIndex(
                                    dst_index).mgr_ipv6, upstream_ecmp_group)
                            entry_hdl_map[
                                "IngressPipeImpl.routing_v6_table"].append(
                                    entry_hdl)
                if len(downstream_ecmp_group) > 0:
                    for dst_index in range(int(sw.name.split("s")[1])):
                        if str("s" +
                               str(dst_index)) in self.nexthopToNeighbors(sw):
                            continue
                        else:
                            entry_hdl = self.writeEcmpGroupRoutingTable(
                                sw,
                                self.getSwitchInstanceFromIndex(
                                    dst_index).mgr_ipv6, downstream_ecmp_group)
                            entry_hdl_map[
                                "IngressPipeImpl.routing_v6_table"].append(
                                    entry_hdl)
                self.deleteEntries(sw, entry_hdl_map)
                self.deleteGroups(sw)

    def controllerMain(self):
        print("Controller connecting to switches ...")
        self.deleteAllEntries()
        self.insertAllEntries()
        # for i in range(self.SWITCH_NUM):
        #     print("sw%d is %s" % (i, self.SWITCH_LIST[i]))
        #     self.getDelayRegister(self.SWITCH_LIST[i])

    ########################################################
    #################### Util FUnctions ####################
    ########################################################
    def getDelayRegister(self, sw):
        return sw.register_read("EgressPipeImpl.link_delay_register", 0)

    def switchNameToIndex(self, sw):
        return int(sw.split("s")[1])

    def getMacByPortName(self, port):
        return netifaces.ifaddresses(port)[netifaces.AF_LINK][0]['addr']

    def getIpv6ByPortName(self, port):
        return netifaces.ifaddresses(port)[
            netifaces.AF_INET6][0]['addr'].split("%")[0]

    def getEntryHandle(self, entry):
        return int(
            str(entry).split("entry_handle=")[1].split(",")[0].split(")")[0])

    def getSwitchMgrFromPort(self, port):
        return port.split("-")[0] + "-mgr"

    def getSwitchInstanceFromPort(self, port):
        for sw in self.SWITCH_LIST:
            if str(sw.name) == str(port.split("-")[0]):
                return sw

    def getSwitchInstanceFromIndex(self, index):
        for sw in self.SWITCH_LIST:
            if int(sw.name.split("s")[1]) == int(index):
                return sw

    def nexthopToNeighbors(self, switch):
        neighbors = []
        for port in switch.next_hop.keys():
            neighbor = str(switch.next_hop.get(port)).split("-")[0]
            neighbors.append(neighbor)
        return list(set(neighbors))


if __name__ == "__main__":
    c = Controller()
    c.controllerMain()