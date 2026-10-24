"""Live room graph: attendees as nodes, shared skills/interests as weighted edges, clusters and bridges.

Edge weight is rarity-weighted (a shared niche skill counts more than a shared "python"), clusters come
from greedy modularity, and bridges are the few attendees whose neighbours span other clusters and who
sit on many shortest paths.
"""
from __future__ import annotations

import math
from collections import Counter

import networkx as nx
from networkx.algorithms.community import greedy_modularity_communities

from .matching import tag_set
from .models import Profile

BRIDGE_SHARE = 0.2   # top 20% of attendees (at least 1, at most 5) are flagged as bridges


def build_room_graph(profiles: list[Profile], max_clusters: int | None = None) -> dict:
    graph = nx.Graph()
    tags: dict[str, set[str]] = {}
    for p in profiles:
        graph.add_node(p.id, name=p.name, headline=p.headline)
        tags[p.id] = tag_set(p.technologies) | tag_set(p.can_offer) | tag_set(p.interests)
    freq: Counter = Counter(t for s in tags.values() for t in s)
    n = len(profiles)

    for i, a in enumerate(profiles):
        for b in profiles[i + 1:]:
            shared = sorted(tags[a.id] & tags[b.id])
            if shared:
                weight = sum(1.0 / freq[t] for t in shared)  # rare shared tags bind tighter
                graph.add_edge(a.id, b.id, weight=round(weight, 3), shared=shared)

    cluster_of: dict[str, int] = {}
    if graph.number_of_edges():
        communities = greedy_modularity_communities(graph, weight="weight", best_n=max_clusters)
        for idx, members in enumerate(communities):
            for node in members:
                cluster_of[node] = idx
    for node in graph.nodes:  # isolated attendees get their own cluster
        cluster_of.setdefault(node, len(set(cluster_of.values())))

    betweenness = nx.betweenness_centrality(graph) if n > 2 else {}
    nodes = []
    for node, data in graph.nodes(data=True):
        other_clusters = {cluster_of[m] for m in graph.neighbors(node)} - {cluster_of[node]}
        nodes.append({
            "id": node,
            "name": data["name"],
            "headline": data["headline"],
            "cluster": cluster_of[node],
            "degree": graph.degree(node),
            "other_clusters": len(other_clusters),
            "betweenness": round(betweenness.get(node, 0.0), 4),
            "bridge_score": round(len(other_clusters) * betweenness.get(node, 0.0), 4),
        })
    nodes.sort(key=lambda x: (-x["bridge_score"], -x["other_clusters"], x["name"]))
    quota = min(5, max(1, math.ceil(n * BRIDGE_SHARE)))
    bridges = [x["id"] for x in nodes[:quota] if x["bridge_score"] > 0]
    for x in nodes:
        x["bridge"] = x["id"] in bridges

    edges = [{"from": a, "to": b, "weight": d["weight"], "shared": d["shared"]} for a, b, d in graph.edges(data=True)]
    return {"nodes": nodes, "edges": edges, "clusters": len(set(cluster_of.values())), "bridges": bridges}
