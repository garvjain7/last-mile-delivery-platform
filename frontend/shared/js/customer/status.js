export const STATUS_LABELS = {
  placed: 'The seller is preparing your parcel',
  sent: 'On its way to our delivery hub',
  pending: 'At our hub, being scheduled',
  assigned: 'Scheduled for delivery',
  out_for_delivery: 'Out for delivery',
  delivered: 'Delivered',
  attempt_failed: 'Delivery attempt unsuccessful',
  returned: 'Returned to the seller',
  cancelled: 'Cancelled',
};

const FLOW = ['Confirmed', 'Picked', 'Loaded', 'Transit', 'Delivered'];
const RAIL_INDEX = {
  placed: 0,
  sent: 1,
  pending: 2,
  assigned: 2,
  out_for_delivery: 3,
  attempt_failed: 3,
  returned: 3,
  cancelled: 0,
  delivered: 4,
};

export function statusLabel(status) {
  return STATUS_LABELS[status] || String(status || 'In progress').replaceAll('_', ' ');
}

export function statusClass(status) {
  if (['delivered'].includes(status)) return 'status-good';
  if (['attempt_failed'].includes(status)) return 'status-warning';
  if (['returned', 'cancelled'].includes(status)) return 'status-bad';
  return 'status-progress';
}

export function buildRail(status) {
  const index = RAIL_INDEX[status] ?? 0;
  return FLOW.map((step, stepIndex) => ({
    status,
    label: step,
    state: stepIndex < index ? 'done' : stepIndex === index ? 'current' : 'upcoming',
  }));
}
