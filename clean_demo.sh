# sudo killall lt-simple_switch
ps -ef | grep simple_switch | grep -v grep | awk '{print $2}' | xargs kill -9
for i in $(seq 0 36)
do
    ip netns del ns$i &> /dev/null
    ip link delete s$i-tin &> /dev/null
    ip link delete s$i-mgr &> /dev/null
    for p in $(seq 0 16)
    do
        ip link delete s$i-eth$p &> /dev/null
    done
done