import os
import re
import sys
import math
import time
import random
import pickle
import threading
import subprocess
import netifaces
import networkx as nx
import matplotlib.pyplot as plt

import include.runtime_data
from include.class_define import SWITCH, thrift_connect

# links = [["eth0:s1-eth1", "eth1:s2-eth1"], ["eth0:s1-host"], ["eth0:s2-host"]]


class Controller():
    def __init__(self):
        self.SWITCH_NUM = 0
        self.TOPO_FILE = "/int/default_topo"
        self.GRAPH = nx.Graph()
        self.LINK_LIST = self.readTopoFile()
        self.SWITCH_LIST = self.switchConnect()
        self.ECMP_GROUP_HANDLER = {}
        self.SWITCH_MEMBER_HANDLER = {}
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
                # print("has ports %s", (self.LINK_LIST[str(index)].keys()))
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
        # print("nodes has %s" % nodes)
        self.GRAPH.add_nodes_from(nodes)

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
        nx.draw(self.GRAPH, with_labels=True, node_color='y',)
        plt.savefig("topo_graph.png")
        plt.show()
        return links

    # IngressPipeImpl.ndp_reply_table(hdr.ndp.target_ipv6_addr)
    def writeNdpReply(self, switch, targetIpv6Addr, targetMac):
        info = switch.table_add_exact(table="IngressPipeImpl.ndp_reply_table",
                                      match_key=[str(targetIpv6Addr)],
                                      match_key_types=['128'],
                                      action="IngressPipeImpl.ndp_ns_to_na",
                                      runtime_data=[str(targetMac)],
                                      runtime_data_types=['48'])
        print("Insert ndp_reply_table on %s successfully: %s", (switch, info))

    # IngressPipeImpl.my_station_table(hdr.ethernet.dst_addr)
    # only a counter counting how many l2 packet reach here
    # same as rmac.hit()
    def writeMyStationTable(self, switch, ethDstAddr):
        info = switch.table_add_exact(table="IngressPipeImpl.my_station_table",
                                      match_key=[str(ethDstAddr)],
                                      match_key_types=['48'],
                                      action="NoAction",
                                      runtime_data=[],
                                      runtime_data_types=[])
        print("Insert my_station_table on %s successfully: %s", (switch, info))

    # IngressPipeImpl.srv6_my_sid(hdr.ipv6.dst_addr)
    def writeSRv6MySidTable(self, switch, localIpv6Addr):
        info = switch.table_add_lpm(table="IngressPipeImpl.srv6_my_sid",
                                    match_key=[str(localIpv6Addr)],
                                    match_key_types=['128'],
                                    action="IngressPipeImpl.srv6_end",
                                    runtime_data=[],
                                    runtime_data_types=[])
        print("Insert srv6_my_sid on %s successfully: %s", (switch, info))

    # IngressPipeImpl.srv6_transit(hdr.ipv6.dst_addr)
    def writeSRv6TransitTable(self, switch, dstIpv6Addr, prefixLength,
                              segmentList):
        info = switch.table_add_lpm(table="IngressPipeImpl.srv6_transit",
                                    match_key=[str(dstIpv6Addr)],
                                    match_key_types=[str(prefixLength)],
                                    action="IngressPipeImpl.srv6_t_insert_2",
                                    runtime_data=segmentList,
                                    runtime_data_types=['128', '128'])
        print("Insert srv6_transit on %s successfully: %s", (switch, info))

    # IngressPipeImpl.l2_exact_table(hdr.ethernet.dst_addr)
    def writeL2ExactTable(self, switch, ethDstAddr, egressPort):
        info = switch.table_add_exact(table="IngressPipeImpl.l2_exact_table",
                                      match_key=[str(ethDstAddr)],
                                      match_key_types=['48'],
                                      action="IngressPipeImpl.set_egress_port",
                                      runtime_data=[str(egressPort)],
                                      runtime_data_types=['9'])
        print("Insert l2_exact_table on %s successfully: %s", (switch, info))

    # IngressPipeImpl.l2_ternary_table(hdr.ethernet.dst_addr)
    def writeL2TernaryTable(self, switch, dstIpv6Addr, nextHopMac):
        info = switch.table_add_lpm(table="IngressPipeImpl.routing_v6_table",
                                    match_key=[str(dstIpv6Addr)],
                                    match_key_types=['128'],
                                    action="IngressPipeImpl.set_next_hop",
                                    runtime_data=[str(nextHopMac)],
                                    runtime_data_types=['48'])
        print("Insert srv6_transit on %s successfully: %s", (switch, info))

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
            match_key_types=['9', '48', '48', '16', '8', '8', '16', '16'],
            action="IngressPipeImpl.send_to_cpu",
            runtime_data=[],
            runtime_data_types=[])
        print("Insert acl_table on %s successfully: %s", (switch, info))

    # IngressPipeImpl.routing_v6_table(hdr.ipv6.dst_addr)
    def writeRoutingIpv6Table(self, switch, dstIpv6Addr, nextHopMac):
        info = switch.table_add_lpm(table="IngressPipeImpl.routing_v6_table",
                                    match_key=[str(dstIpv6Addr)],
                                    match_key_types=['128'],
                                    action="IngressPipeImpl.set_next_hop",
                                    runtime_data=[str(nextHopMac)],
                                    runtime_data_types=['48'])
        print("Insert routing_v6_table on %s successfully: %s", (switch, info))

    def writeEcmpGroupRoutingTable(self, switch, dstIpv6Addr):
        info = switch.add_entry_to_group(
            table_name="IngressPipeImpl.routing_v6_table",
            match_key=[str(dstIpv6Addr)],
            match_key_types=["128"],
            grp_handle=self.ECMP_GROUP_HANDLER[switch])
        print("Insert routing_v6_table on %s successfully: %s", (switch, info))

    def createEcmpSelectorGroup(self, switch, groupSwitches):
        info = switch.create_group("IngressPipeImpl.ecmp_selector")
        self.ECMP_GROUP_HANDLER[str(switch)] = info
        print("Create ecmp_selector group on %s successfully: %s",
              (switch, info))
        # add set_routeid action to member
        for i in range(len(groupSwitches)):
            info = switch.act_prof_add_member(
                action_profile_name="IngressPipeImpl.ecmp_selector",
                action_name="IngressPipeImpl.set_next_hop",
                runtime_data=[str(groupSwitches[i].mgr_mac)],
                runtime_data_types=['48'])
            self.SWITCH_MEMBER_HANDLER[str(switch)] = info
            print("Add switch:%s to group on %s successfully: %s",
                  (groupSwitches[i], switch, info))
            switch.add_member_to_group(
                action_profile_name="IngressPipeImpl.ecmp_selector",
                mbr_handle=self.SWITCH_MEMBER_HANDLER[str(switch)],
                grp_handle=self.ECMP_GROUP_HANDLER[str(switch)])

    def insertEntries(self):
        for sw in self.SWITCH_LIST:
            # get from config file
            self.writeNdpReply(sw, sw.mgr_ipv6, sw.mgr_mac)
            self.writeL2ExactTable(sw, sw.mgr_mac, sw.port)
            # self.writeL2TernaryTable()
            self.writeSRv6MySidTable(sw, sw.mgr_ipv6)
            # self.writeSRv6TransitTable()
            self.writeMyStationTable(sw, sw.mgr_mac)
            # self.writeAclTable()
            for sw_dst in self.SWITCH_LIST:
                if sw is not sw_dst:
                    self.writeRoutingIpv6Table(
                        sw, sw_dst.mgr_ipv6,
                        sw.nextPort[sw_dst])  # nextPort = {sw;port}
                    self.writeEcmpGroupRoutingTable(sw, sw_dst.mgr_ipv6)

    def controllerMain(self):
        print("Controller connecting to switches ...")
        for i in range(self.SWITCH_NUM):
            # print("sw%d is %s", (i, self.SWITCH_LIST[i]))
            self.getDelayRegister(self.SWITCH_LIST[i])
            # self.insertEntries()
    def getDelayRegister(self, sw):
        s = sw.register_read("EgressPipeImpl.link_delay_register", 0)
        print(s)


if __name__ == "__main__":
    c = Controller()
    # c.controllerMain()