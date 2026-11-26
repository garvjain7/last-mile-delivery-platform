import assert from "node:assert/strict";
import test from "node:test";

import { isPickupConfirmedForRoute } from "../../frontend/driver-app/js/services/route-state.mjs";

test("resuming a progressed route does not ask the driver to pick up parcels again", () => {
    const route = {
        route_id: "route-1",
        stops: [{ status: "delivered" }, { status: "failed" }, { status: "pending" }]
    };

    assert.equal(isPickupConfirmedForRoute(route, { route_id: "route-1", pickedUp: false }), true);
});

test("a newly started route still requires pickup confirmation", () => {
    const route = {
        route_id: "route-1",
        stops: [{ status: "pending" }, { status: "pending" }]
    };

    assert.equal(isPickupConfirmedForRoute(route, null), false);
});

test("saved pickup state is retained only for the same route", () => {
    const route = { route_id: "route-2", stops: [{ status: "pending" }] };

    assert.equal(isPickupConfirmedForRoute(route, { route_id: "route-2", pickedUp: true }), true);
    assert.equal(isPickupConfirmedForRoute(route, { route_id: "route-1", pickedUp: true }), false);
});
