import assert from "node:assert/strict";
import test from "node:test";

import { applyEventCommitStatuses } from "../../frontend/driver-app/js/services/driver-event-status.mjs";

test("only committed events are deleted; rejected events retain their reason", async () => {
    const records = new Map([
        ["event-committed", { event_id: "event-committed", sync_status: "awaiting_commit" }],
        ["event-rejected", { event_id: "event-rejected", sync_status: "awaiting_commit" }],
        ["event-pending", { event_id: "event-pending", sync_status: "awaiting_commit" }]
    ]);
    const transact = async (_mode, action) => action({
        delete: (eventId) => records.delete(eventId),
        put: (record) => records.set(record.event_id, record)
    });

    const result = await applyEventCommitStatuses(
        [...records.values()],
        [
            { event_id: "event-committed", status: "committed" },
            { event_id: "event-rejected", status: "rejected", reject_reason: "stale route" },
            { event_id: "event-pending", status: "pending" }
        ],
        transact
    );

    assert.deepEqual(result, { committed: 1, rejected: 1 });
    assert.equal(records.has("event-committed"), false);
    assert.deepEqual(records.get("event-rejected"), {
        event_id: "event-rejected",
        sync_status: "rejected",
        reject_reason: "stale route"
    });
    assert.equal(records.get("event-pending").sync_status, "awaiting_commit");
});

test("an unknown event status cannot mutate the local outbox", async () => {
    const record = { event_id: "event-1", sync_status: "awaiting_commit" };
    const transact = async () => assert.fail("Invalid statuses must not modify the outbox.");

    await assert.rejects(
        applyEventCommitStatuses(
            [record],
            [{ event_id: "another-event", status: "committed" }],
            transact
        ),
        /invalid event status/
    );
});
