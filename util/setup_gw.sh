#!/usr/bin/env bash
num=$1
intf=$2
ip link set dev $intf down
ip link set dev $intf address 10:00:11:11:$num:11
ip -6 addr add 2001::$num:202 dev $intf
ip link set dev $intf up