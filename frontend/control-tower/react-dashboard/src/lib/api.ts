
const API_BASE_URL = "http://127.0.0.1:8000";

export interface Driver {
  driver_id: string;
  driver_name?: string;
  vehicle_id?: string | null;
  status?: string;

  // Live Redis fields
  lat?: number | string;
  lng?: number | string;
  latitude?: number | string;
  longitude?: number | string;
  speed?: number | string;
  last_ping?: string;
  timestamp?: string;
last_updated?: string;
  current_route_id?: string;
  stale?: boolean;
}

export interface RouteStop {
  stop_id?: string;
  order_id: string;
  recipient_name?: string;
  sequence?: number;
  lat?: number;
  lng?: number;
  status?: string;
  stop_status?: string;
  order_status?: string;
  eta?: string;
}

export interface Route {
  route_id: string;
  version?: number | string;
  driver_id?: string;
  vehicle_id?: string;
  status?: string;
  total_distance_m?: number | null;
  total_duration_s?: number | null;
  total_stops?: number;
  stops?: RouteStop[];
}

export interface DashboardStats {
  total_orders: number;
  delivered_orders: number;
  pending_orders: number;
  out_for_delivery: number;
  total_drivers: number;
  available_drivers: number;
  active_routes: number;
  completed_routes: number;
  total_vehicles: number;
}

export interface ShipmentEvent {
  from_status: string | null;
  to_status: string;
  occurred_at: string;
}

export interface OrderEvent {
  from_status: string | null;
  to_status: string;
  occurred_at: string;
}

export interface Shipment {
  order_id: string;
  merchant_order_ref: string | null;
  recipient_name: string | null;
  locality: string | null;
  status: string;
  created_at: string;
  events: OrderEvent[];
  stop_status: string | null;
}

export interface DeliveryException {
  exception_id: string;
  order_id: string;
  route_id: string | null;
  driver_id: string | null;
  recipient_name: string | null;
  driver_name: string | null;
  failure_reason: string;
  notes: string | null;
  return_to_hub: boolean;
  created_at: string;
}


export interface DashboardData {
  stats: DashboardStats;
  drivers: Driver[];
  routes: Route[];
  shipments: Shipment[];
  warehouses: WarehouseData[];
  exceptions?: DeliveryException[];
}

export interface WarehouseData {
  warehouse_id: string;
  code: string;
  name: string;
  address: string;
  is_active: boolean;
  total_orders: number;
  out_for_delivery: number;
  delivered_orders: number;
}

export interface OrderRecord {
  id: string;
  merchant_order_ref: string;
  status: string;
  recipient_name: string;
  delivery_address: string;
  created_at: string;
}

export async function getDashboardData(): Promise<DashboardData> {
  const response = await fetch(`${API_BASE_URL}/dashboard/data`);

  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }

  return response.json();
}
export async function requestRescue(routeId: string) {
  const response = await fetch(
    `${API_BASE_URL}/rescue/${routeId}`,
    {
      method: "POST",
    }
  );

  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new Error(
      error?.detail || "Could not request rescue"
    );
  }

  return response.json();
}

export async function getOrders(): Promise<OrderRecord[]> {
  const response = await fetch(`${API_BASE_URL}/orders`);

  if (!response.ok) {
    throw new Error(`Orders API failed: ${response.status}`);
  }

  return response.json();
}

export interface DriverRecord {
  user_id: string;
  vehicle_id: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export async function getDrivers(): Promise<DriverRecord[]> {
  const response = await fetch(`${API_BASE_URL}/drivers`);

  if (!response.ok) {
    throw new Error(`Drivers API failed: ${response.status}`);
  }

  return response.json();
}

export async function getDriversByStatus(
  status: string
): Promise<DriverRecord[]> {
  const response = await fetch(
    `${API_BASE_URL}/drivers/status/${encodeURIComponent(status)}`
  );

  if (!response.ok) {
    throw new Error(`Driver status API failed: ${response.status}`);
  }

  return response.json();
}

export async function updateDriverStatus(
  userId: string,
  status: string
): Promise<DriverRecord> {
  const response = await fetch(
    `${API_BASE_URL}/drivers/${encodeURIComponent(userId)}/status?status=${encodeURIComponent(status)}`,
    {
      method: "PATCH",
    }
  );

  if (!response.ok) {
    throw new Error(`Driver update failed: ${response.status}`);
  }

  return response.json();
}