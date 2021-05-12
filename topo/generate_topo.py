import itertools
import matplotlib.pyplot as plt
import networkx as nx

from networkx.utils import pairwise

subset_sizes = [8, 4, 4, 2, 2, 4, 4, 8]
subset_color = [
    "gold",
    "violet",
    "violet",
    "limegreen",
    "limegreen",
    "violet",
    "violet",
    "darkorange",
]


def multilayered_graph(*subset_sizes):
    extents = pairwise(itertools.accumulate((0,) + subset_sizes))
    layers = [range(start, end) for start, end in extents]
    G = nx.Graph()
    for (i, layer) in enumerate(layers):
        G.add_nodes_from(layer, layer=i)
    for layer1, layer2 in pairwise(layers):
        G.add_edges_from(itertools.product(layer1, layer2))
    layer1 = layers[0]
    layer2 = layers[1]
    # for tor in layer1:
    #     for s1 in range(layer2[0]
    # print("layer1 = %s, layer2 = %s" % (type(layer1), layer2))
    return G


G = multilayered_graph(*subset_sizes)
nodes = G.nodes()
edges = G.edges()
links_map = {}
with open("generated_topo", "w+") as f:
    for n in nodes:
        f.write("s" + str(n))
        f.write(",")
        links_map[n] = 0
    f.write("\n")
    # print(links_map)
    for e in edges:
        src, dst = e[0], e[1]
        src_cur = links_map.get(src)
        dst_cur = links_map.get(dst)
        # print(src_cur, dst_cur)
        f.write("s%d:%d-s%d:%d" % (src, src_cur, dst, dst_cur))
        f.write("\n")
        links_map[src] = src_cur + 1
        links_map[dst] = dst_cur + 1

color = [subset_color[data["layer"]] for v, data in G.nodes(data=True)]
pos = nx.multipartite_layout(G, subset_key="layer")
plt.figure(figsize=(8, 8))
nx.draw(G, pos, node_color=color, with_labels=True)
plt.axis("equal")
plt.show()