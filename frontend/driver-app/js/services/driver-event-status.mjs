export async function applyEventCommitStatuses(records, events, outboxTransaction) {
    if (!Array.isArray(events)) {
        throw new Error("The event status service returned an invalid response.");
    }

    const recordsById = new Map(records.map((record) => [record.event_id, record]));
    const seenEventIds = new Set();
    let committed = 0;
    let rejected = 0;
    for (const result of events) {
        if (
            !result
            || !recordsById.has(result.event_id)
            || seenEventIds.has(result.event_id)
            || !["committed", "rejected", "pending"].includes(result.status)
        ) {
            throw new Error("The event status service returned an invalid event status.");
        }
        seenEventIds.add(result.event_id);
        const record = recordsById.get(result.event_id);
        if (result.status === "committed") {
            await outboxTransaction("readwrite", (store) => store.delete(record.event_id));
            committed += 1;
        } else if (result.status === "rejected") {
            await outboxTransaction("readwrite", (store) => store.put({
                ...record,
                sync_status: "rejected",
                reject_reason: result.reject_reason || "The server rejected this event."
            }));
            rejected += 1;
        }
    }
    return { committed, rejected };
}
