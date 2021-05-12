- Build p4 in Docker [/int/p4src]:
```
p4c --target bmv2 --arch v1model main.p4
```
- Setup envoriment [/int]:
```
python run_demo.py topo/tree_topo
```
- Use Controller to add entries [/int]:
```
python controller.py
```
- Clean everything [/int]:
```
bash clean_demo.sh
```
- Generate some traffic in network namespace [what ever]:
1. Login network namespace  `ip netns exec ns0 bash`
2. Check interfaces  `ifconfig`
3. Ping some host with IPv6 address: `ping6 2001::33:101`
4. Use iperf test UDP: 
    - In Server: `iperf –s -u –p 521 –i 1 -V`
    - In Client: `iperf -c 2001::33:101 -u -p 521 -i 1 -t 10 -V`