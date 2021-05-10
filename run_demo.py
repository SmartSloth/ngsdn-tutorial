import argparse
import subprocess
import time


def setup_veth(veth0, veth1):
    subprocess.Popen("bash /int/util/veth_setup.sh %s %s" % (veth0, veth1),
                     shell=True).wait()


def bind_host(veth0, veth1, num):
    subprocess.Popen("bash /int/util/bind_host.sh %s %s %s" % (veth0, veth1, num),
                     shell=True).wait()


BMV2_PATH = "/behavioral-model/"
SWITCH_PATH = "/usr/local/bin/simple_switch "
CLI_PATH = BMV2_PATH + "targets/simple_switch/sswitch_CLI "
P4_JSON = "/int/p4src/main.json"

parser = argparse.ArgumentParser()
parser.add_argument("topo_file", help="topo file")
parser.add_argument("-p", "--p4-file", help="p4 file path")
parser.add_argument("-t",
                    "--thrift-port",
                    help="thrift port of s0, default is 9000",
                    default=9000)
parser.add_argument("-j",
                    "--json-file",
                    help="json file name, default is t.json",
                    default="t.json")
parser.add_argument("-c",
                    "--console-log",
                    help="print log of simple switch",
                    action='store_true')
parser.add_argument("-m",
                    "--command-file",
                    help="use sx-commands.txt as init entry",
                    action='store_true')
args = parser.parse_args()
args.thrift_port = int(args.thrift_port)
if args.p4_file:
    subprocess.Popen("p4c --target bmv2 --arch v1model --std p4-16 %s" %
                     (args.p4_file),
                     shell=True).wait()

with open(args.topo_file, "r") as f:
    cmds = f.readlines()

tors = cmds[:2][0][:-1].split(":")[-1]
core = cmds[:2][1][:-1].split(":")[-1]
if tors != "":
    tors = [_[1:] for _ in tors.split(",")]
    sws = tors
if core != "":
    core = [_[1:] for _ in core.split(",")]
    sws = sws + core
# print("********** swss has: %s", str(sws))
# print("********** tors has: %s", str(tors))
# print("********** core has: %s", str(core))

links = dict(zip(sws, [{} for _ in sws]))
topo = cmds[2:]
for s in sws:
    setup_veth("s%s-int" % (s, ),
               "s%s-mgr" % (s, ))  # clone to controller, port 11
for s in tors:
    bind_host("s%s-trf" % (s, ), "s%s-tin" % (s, ),
              "%s" % (s, ))  # connect to host, port 10
for t in topo:
    s1 = t[:-1].split("-")[0]
    s2 = t[:-1].split("-")[1]
    s1_name = s1.split(":")[0][1:]
    s1_iface = s1.split(":")[1]
    s2_name = s2.split(":")[0][1:]
    s2_iface = s2.split(":")[1]
    setup_veth("s%s-eth%s" % (s1_name, s1_iface),
               "s%s-eth%s" % (s2_name, s2_iface))
    links[s1_name][s1_iface] = "s%s-eth%s" % (s1_name, s1_iface)
    links[s2_name][s2_iface] = "s%s-eth%s" % (s2_name, s2_iface)
# print("********** links has: %s", str(links))
switch_args_list = []
for i in sws:
    switch_args = "--thrift-port %d --device-id %s " % (args.thrift_port +
                                                        int(i), i)
    if i in tors:
        switch_args += "-i 10@s%s-tin " % (i, ) # connect to host, port 10
    for j, p in links[i].items():
        switch_args += "-i %s@%s " % (j, p)
    switch_args += "-i 11@s%s-mgr " % (i, ) # clone to controller, port 11
    if args.console_log:
        switch_args += "--log-console "
    # if i == 8:
    #     switch_args += "--nanolog ipv:///tmp/bm-log.ipc "
    switch_args += P4_JSON
    switch_args_list.append(switch_args)
# print(switch_args_list)

for i in range(len(sws)):
    # print("########## setup bmv2: %s", SWITCH_PATH + switch_args_list[i])
    subprocess.Popen(SWITCH_PATH + switch_args_list[i], shell=True)

time.sleep(1)
if args.command_file:
    for i in sws:
        subprocess.Popen(CLI_PATH + "%s %d < command/s%s-commands.txt" %
                         (args.json_file, args.thrift_port + int(i), i),
                         shell=True).wait()