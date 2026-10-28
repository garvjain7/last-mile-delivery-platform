"""
Step 3 — validate a knowledge graph against the SHACL data contract.

    python data/pipeline/validate_kg.py data/build/world.ttl [--report data/build/shacl_report.txt]

Exit code 0 = conforms. The ontology is loaded alongside the data so SHACL
can see class hierarchy (e.g. lm:Driver ⊑ lm:User) and lm:allowedNext.
"""

import argparse
import sys
import time
from collections import Counter

from pyshacl import validate
from rdflib import Graph, Namespace

SH = Namespace("http://www.w3.org/ns/shacl#")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data")
    ap.add_argument("--shapes", default="data/ontology/shapes.ttl")
    ap.add_argument("--ontology", default="data/ontology/lastmile.ttl")
    ap.add_argument("--report")
    args = ap.parse_args()

    t0 = time.time()
    data = Graph().parse(args.data)
    data.parse(args.ontology)
    shapes = Graph().parse(args.shapes)
    print(f"loaded {len(data):,} triples in {time.time() - t0:.0f}s")

    t0 = time.time()
    # No inference pass: SHACL already follows rdfs:subClassOf for
    # sh:targetClass/sh:class, and RDFS inference roughly doubles run time.
    conforms, report_graph, report_text = validate(
        data, shacl_graph=shapes, inference="none", advanced=True, allow_warnings=True)
    print(f"validated in {time.time() - t0:.0f}s — conforms={conforms}")
    if not isinstance(report_graph, Graph):   # the shapes themselves are invalid
        print(report_text)
        sys.exit(2)

    messages = Counter(str(m) for m in report_graph.objects(None, SH.resultMessage))
    for msg, n in messages.most_common(25):
        print(f"{n:7}  {msg}")
    if args.report:
        with open(args.report, "w") as fh:
            fh.write(report_text)
    sys.exit(0 if conforms else 1)


if __name__ == "__main__":
    main()
