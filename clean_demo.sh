# sudo killall lt-simple_switch
ps -ef | grep simple_switch | grep -v grep | awk '{print $2}' | xargs kill -9
for i in $(seq 0 19)
do
    ip netns del ns$i
    ip link delete s$i-tin
    ip link delete s$i-mgr
    ip link delete s$i-eth0
    ip link delete s$i-eth1
    ip link delete s$i-eth2
    ip link delete s$i-eth3
    ip link delete s$i-eth4
    ip link delete s$i-eth5
done