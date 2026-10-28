"""The SHACL contract must accept a valid mini-world and reject each kind of
broken data. Each test breaks exactly one thing and checks the right rule fires."""

from pathlib import Path

import pytest
from pyshacl import validate
from rdflib import Graph, Literal, Namespace

LM = Namespace("https://lastmile.example.org/ontology#")
SH = Namespace("http://www.w3.org/ns/shacl#")
ONTOLOGY = Path("data/ontology")

WORLD = """
@prefix lm: <https://lastmile.example.org/ontology#> .
@prefix id: <https://lastmile.example.org/id/> .
@prefix geo: <http://www.opengis.net/ont/geosparql#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .

lm:Dataset a lm:DatasetRoot .

id:wh a lm:Warehouse ; lm:code "RPR-T" ; lm:name "Test Hub" ; lm:address "Urla, Raipur 492003" ;
    lm:isActive true ; lm:pincode "492003" ; geo:hasGeometry id:wh-g .
id:wh-g geo:asWKT "POINT(81.61 21.31)"^^geo:wktLiteral .

id:veh a lm:Vehicle ; lm:registration_number "CG04MA0001" ; lm:vehicleType lm:two_wheeler ;
    lm:max_volume_m3 "0.1200"^^xsd:decimal ; lm:max_weight_kg "25.000"^^xsd:decimal .

id:drv a lm:Driver ; lm:name "Test Rider" ; lm:email "rider@lastmile.test" ; lm:phone "+919000000001" ;
    lm:role "driver" ; lm:vehicle id:veh ; lm:warehouse id:wh ; lm:driverStatus "available" .

id:mer a lm:Merchant ; lm:name "Test Shop" .
id:mu a lm:MerchantUser ; lm:name "Shop Owner" ; lm:email "shop@lastmile.test" ; lm:role "merchant" ; lm:memberOf id:mer .

id:o1 a lm:Order ; lm:merchant id:mer ; lm:merchant_order_ref "RPR-000001" ; lm:tracking_token "ABCDEFGHIJ" ;
    lm:recipient_name "Asha Verma" ; lm:recipient_phone "+919000000002" ;
    lm:delivery_address "H.No. 12, Near Jaistambh Chowk, Raipur, Chhattisgarh 492001" ;
    lm:deliveryLocation id:o1-loc ; lm:pincode "492001" ; lm:locality "Chhotapara" ; lm:digipin "39J49L5P6T" ;
    lm:weight_kg "1.200"^^xsd:decimal ; lm:volume_m3 "0.0050"^^xsd:decimal ; lm:planned_service_time_s 60 ;
    lm:payment_mode "cod" ; lm:cod_amount_inr "650.00"^^xsd:decimal ;
    lm:status lm:delivered ; lm:warehouse id:wh ; lm:created_at "2026-10-27T09:00:00+00:00"^^xsd:dateTime ;
    lm:derivationRule "test fixture" .
id:o1-loc a lm:DeliveryLocation ; geo:hasGeometry id:o1-g .
id:o1-g geo:asWKT "POINT(81.63 21.24)"^^geo:wktLiteral .

id:e1 a lm:OrderStatusChange ; lm:order id:o1 ; lm:sequenceNo 1 ; lm:toStatus lm:placed ; lm:occurred_at "2026-10-27T09:00:00+00:00"^^xsd:dateTime .
id:e2 a lm:OrderStatusChange ; lm:order id:o1 ; lm:sequenceNo 2 ; lm:fromStatus lm:placed ; lm:toStatus lm:sent ; lm:occurred_at "2026-10-27T10:00:00+00:00"^^xsd:dateTime .
id:e3 a lm:OrderStatusChange ; lm:order id:o1 ; lm:sequenceNo 3 ; lm:fromStatus lm:sent ; lm:toStatus lm:pending ; lm:occurred_at "2026-10-27T20:00:00+00:00"^^xsd:dateTime .
id:e4 a lm:OrderStatusChange ; lm:order id:o1 ; lm:sequenceNo 4 ; lm:fromStatus lm:pending ; lm:toStatus lm:assigned ; lm:occurred_at "2026-10-28T02:30:00+00:00"^^xsd:dateTime .
id:e5 a lm:OrderStatusChange ; lm:order id:o1 ; lm:sequenceNo 5 ; lm:fromStatus lm:assigned ; lm:toStatus lm:out_for_delivery ; lm:occurred_at "2026-10-28T03:00:00+00:00"^^xsd:dateTime .
id:e6 a lm:OrderStatusChange ; lm:order id:o1 ; lm:sequenceNo 6 ; lm:fromStatus lm:out_for_delivery ; lm:toStatus lm:delivered ; lm:isLatest true ; lm:occurred_at "2026-10-28T04:00:00+00:00"^^xsd:dateTime .

id:r1 a lm:Route ; lm:warehouse id:wh ; lm:driver id:drv ; lm:vehicle id:veh ; lm:status lm:route_completed .
id:s1 a lm:RouteStop ; lm:route id:r1 ; lm:order id:o1 ; lm:sequence "1"^^xsd:positiveInteger ; lm:status lm:stop_delivered ;
    lm:planned_arrival_at "2026-10-28T03:55:00+00:00"^^xsd:dateTime ; lm:completed_at "2026-10-28T04:00:00+00:00"^^xsd:dateTime .
id:a1 a lm:DeliveryAttempt ; lm:order id:o1 ; lm:routeStop id:s1 ; lm:driver id:drv ; lm:outcome "delivered" ;
    lm:client_event_id "11111111-1111-1111-1111-111111111111" ; lm:occurred_at "2026-10-28T04:00:00+00:00"^^xsd:dateTime .
"""

ID = Namespace("https://lastmile.example.org/id/")


def run(graph):
    graph.parse(ONTOLOGY / "lastmile.ttl")
    conforms, report, _ = validate(graph, shacl_graph=Graph().parse(ONTOLOGY / "shapes.ttl"),
                                   inference="none", advanced=True)
    return conforms, {str(m) for m in report.objects(None, SH.resultMessage)}


def world():
    return Graph().parse(data=WORLD, format="turtle")


def test_valid_world_conforms():
    conforms, messages = run(world())
    assert conforms, messages


def _remove(g, s, p):
    g.remove((s, p, None))
    return g


@pytest.mark.parametrize("break_it, expected", [
    (lambda g: g.remove((ID.a1, None, None)) or g, "Delivered/failed/returned order has no DeliveryAttempt."),
    (lambda g: g.set((ID.e5, LM.toStatus, LM.delivered)) or g, "Illegal lifecycle transition (not in lm:allowedNext)."),
    (lambda g: _remove(g, ID.o1, LM.cod_amount_inr), "COD order must have a COD amount; prepaid must not."),
    (lambda g: g.set((ID.o1, LM.status, LM.returned)) or g, "Order status differs from its latest history event."),
    (lambda g: g.set((ID.o1, LM.weight_kg, Literal("30.000", datatype=Namespace("http://www.w3.org/2001/XMLSchema#").decimal))) or g,
     "Route load exceeds vehicle weight capacity."),
    (lambda g: g.set((ID.e4, LM.occurred_at, Literal("2026-10-26T00:00:00+00:00",
                      datatype=Namespace("http://www.w3.org/2001/XMLSchema#").dateTime))) or g,
     "History events are not in time order."),
    (lambda g: _remove(g, ID.o1, LM.warehouse), "Order past 'placed' must have a warehouse; a 'placed'/'cancelled' order must not."),
])
def test_each_broken_rule_is_reported(break_it, expected):
    conforms, messages = run(break_it(world()))
    assert not conforms
    assert expected in messages, messages


def test_bad_pincode_and_digipin_are_rejected():
    g = world()
    g.set((ID.o1, LM.pincode, Literal("49200")))
    g.set((ID.o1, LM.digipin, Literal("39J49L5P60")))
    conforms, _ = run(g)
    assert not conforms
