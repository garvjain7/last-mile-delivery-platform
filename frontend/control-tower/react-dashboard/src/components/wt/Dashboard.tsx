import {
  getDashboardData,
  requestRescue,
  getOrders,
  getDrivers,
  getDriversByStatus,
  updateDriverStatus,
  type DashboardData,
  type OrderRecord,
  type DriverRecord,
} from "@/lib/api";
import { useMemo, useRef, useState, useEffect } from "react";
import {
  Search, Bell, ChevronDown, Package, Truck as TruckIcon, Clock, Boxes, Plus, Minus, RotateCcw, RotateCw, Home,
  Sun, Moon, RefreshCw, ArrowUp, ChevronRight, ClipboardCheck, PackageCheck, Container, CheckCircle2, X, UserRound, AlertTriangle, Crosshair, Forklift as ForkliftIcon, Box,
} from "lucide-react";
import { WarehouseScene, type Pick, type SceneHandle } from "./WarehouseScene";
import {
  warehouses, baseInventory, trucks, forklifts, shipmentSteps, stockStatus, filterInventory, BACKEND_CONNECTED, WAITING, type InventoryItem,
} from "@/lib/warehouse-data";

const statusClass = (s: string) =>
  s === "In Stock" || s === "Available" ? "chip-ok" : s === "Low Stock" || s === "En route" || s === "Waiting" || s === "No data" ? "chip-warn" : s === "Loading" ? "chip-info" : "chip-bad";

export function Dashboard() {
  const [shipments, setShipments] = useState<OrderRecord[]>([]);
  const [driverRecords, setDriverRecords] = useState<DriverRecord[]>([]);
const [driverFilter, setDriverFilter] = useState("all");
const [driverLoading, setDriverLoading] = useState(false);
const [driverError, setDriverError] = useState("");
const [updatingDriver, setUpdatingDriver] = useState<string | null>(null);
  const [whId, setWhId] = useState("");
  const [whOpen, setWhOpen] = useState(false);
  
  const [query, setQuery] = useState("");
  const [night, setNight] = useState(false);
  const [pick, setPick] = useState<Pick>(null);
const [tab, setTab] = useState<
  "docks" | "forklifts" | "trucks" | "drivers" | "routes"
>("drivers");  const [inventory, setInventory] = useState<InventoryItem[]>(baseInventory);
  const [spinning, setSpinning] = useState(false);
  const [notifOpen, setNotifOpen] = useState(false);
  const [ready, setReady] = useState(false);
  const [clock, setClock] = useState("");
  const scene = useRef<SceneHandle>(null);
  const [dashboardData, setDashboardData] = useState<DashboardData>({
  stats: {
    total_orders: 0,
    delivered_orders: 0,
    pending_orders: 0,
    out_for_delivery: 0,
    total_drivers: 0,
    available_drivers: 0,
    active_routes: 0,
    completed_routes: 0,
    total_vehicles: 0,
  },
  drivers: [],
  routes: [],
  shipments: [],
  warehouses: [],
});

const dbWarehouse = dashboardData.warehouses.find(
  (w) => w.code === whId
);
useEffect(() => {
  let active = true;

  async function loadDrivers() {
    setDriverLoading(true);
    setDriverError("");

    try {
      const data =
        driverFilter === "all"
          ? await getDrivers()
          : await getDriversByStatus(driverFilter);

      if (active) {
        setDriverRecords(data);
      }
    } catch (error) {
      console.error("Driver API error:", error);

      if (active) {
        setDriverError("Could not fetch drivers");
      }
    } finally {
      if (active) {
        setDriverLoading(false);
      }
    }
  }

  loadDrivers();

  return () => {
    active = false;
  };
}, [driverFilter]);

async function handleDriverStatusUpdate(
  userId: string,
  status: string
) {
  setUpdatingDriver(userId);
  setDriverError("");

  try {
    await updateDriverStatus(userId, status);

    const data =
      driverFilter === "all"
        ? await getDrivers()
        : await getDriversByStatus(driverFilter);

    setDriverRecords(data);

    const refreshedDashboard = await getDashboardData();
    setDashboardData(refreshedDashboard);

  } catch (error) {
    console.error("Driver update error:", error);
    setDriverError("Could not update or refresh driver data");
  } finally {
    setUpdatingDriver(null);
  }
}

const wh = dbWarehouse
  ? {
      id: dbWarehouse.code,
      name: dbWarehouse.name,
      address: dbWarehouse.address,
      stock: 0,
      capacity: 0,
      baysBusy: 0,
      bays: 0,
      outbound: dbWarehouse.out_for_delivery,
      putaways: 0,
    }
  : warehouses.find((w) => w.id === whId) ?? warehouses[0]!;

const [selectedShipmentId, setSelectedShipmentId] = useState("");
const selectedShipment =
  dashboardData.shipments.find(
    (s) => s.order_id === selectedShipmentId
  ) ?? dashboardData.shipments[0];

const [apiError, setApiError] = useState("");


      
useEffect(() => {
  let active = true;

  const loadDashboard = async () => {
    try {
      const data = await getDashboardData();

      if (active) {
        setDashboardData(data);
       
setShipments(
  (data.shipments ?? []).map((shipment) => ({
    ...shipment,
    id: shipment.order_id,
    merchant_order_ref: shipment.merchant_order_ref ?? "",
    recipient_name: shipment.recipient_name ?? "",
    delivery_address: shipment.locality ?? "",
  }))
);

        if (data.warehouses?.length > 0) {
          const activeWarehouse = data.warehouses.find(
            (w) => w.is_active
          );

          const warehouseCode =
            activeWarehouse?.code ?? data.warehouses[0]?.code;

          if (warehouseCode) {
            setWhId(warehouseCode);
          }
        }

        setApiError("");
      }
    } catch (error) {
      console.error("Dashboard API error:", error);

      if (active) {
        setApiError("Could not connect to backend");
      }
    }
  };

  loadDashboard();

  const interval = window.setInterval(loadDashboard, 10000);

  return () => {
    active = false;
    window.clearInterval(interval);
  };
}, []);


  useEffect(() => {
    const tick = () => setClock(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }));
    tick(); const i = setInterval(tick, 30000); return () => clearInterval(i);
  }, []);

  const filtered = useMemo(() => filterInventory(inventory, query), [inventory, query]);
  const alerts = !BACKEND_CONNECTED ? [] : inventory.filter((i) => stockStatus(i) !== "In Stock");

  const refresh = () => {
    setSpinning(true);
    setInventory(baseInventory);
    setTimeout(() => setSpinning(false), 700);
  };

  const selTruck = pick?.type === "truck" ? trucks.find((t) => t.id === pick.id) : null;
  const selFork = pick?.type === "forklift" ? forklifts.find((f) => f.id === pick.id) : null;

  return (
    <div className={`min-h-screen bg-background text-foreground ${night ? "dark" : ""}`}>
      <div className="flex min-h-screen flex-col bg-background">
        {/* NAV */}
        <header className="z-30 flex flex-wrap items-center gap-3 border-b border-border bg-card px-4 py-3 lg:px-6">
          <div className="flex items-center gap-2 font-display text-xl font-bold">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-primary text-primary-foreground"><Box className="h-5 w-5" /></span>
            LastMileDelivery
          </div>
          <label className="order-last flex w-full items-center gap-2 rounded-xl border border-border bg-background px-3 py-2 md:order-none md:ml-6 md:w-auto md:flex-1 md:max-w-md">
            <Search className="h-4 w-4 text-muted-foreground" />
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search inventory items, SKUs…" className="w-full bg-transparent text-sm outline-none placeholder:text-muted-foreground" />
            {query && <button onClick={() => setQuery("")} aria-label="Clear search"><X className="h-4 w-4 text-muted-foreground" /></button>}
          </label>
          <div className="ml-auto flex items-center gap-2">
            <div className="relative">
              <button onClick={() => setWhOpen((o) => !o)} className="flex items-center gap-2 rounded-xl border border-border bg-background px-2 py-1.5 text-left">
                <span className="rounded-md bg-primary px-1.5 py-0.5 text-xs font-bold text-primary-foreground">{wh.id}</span>
                <span className="hidden sm:block">
                  <span className="block text-sm font-semibold leading-tight">{wh.name}</span>
                  <span className="block text-xs text-muted-foreground">
  {dbWarehouse
    ? `${dbWarehouse.total_orders.toLocaleString()} total orders`
    : "Warehouse information unavailable"}
</span>
                </span>
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              </button>
              {whOpen && (
                <div className="absolute right-0 top-full z-40 mt-2 w-64 rounded-xl border border-border bg-popover p-1 shadow-panel">
                  {dashboardData.warehouses.map((w) => (
                    <button
                      key={w.warehouse_id}
                      onClick={() => {
                        setWhId(w.code);
                        setWhOpen(false);
                      }}
                      className={`flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm hover:bg-accent ${
                        w.code === whId ? "bg-accent" : ""
                      }`}
                    >
                      <span className="rounded bg-primary px-1.5 text-xs font-bold text-primary-foreground">
                        {w.code}
                      </span>
                      {w.name}
                      {!w.is_active && (
                        <span className="text-xs text-muted-foreground">
                          (Closed)
                        </span>
                      )}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <span className="hidden items-center gap-1.5 rounded-full bg-success/15 px-3 py-1 text-xs font-semibold text-success sm:flex">
  <span className="h-2 w-2 rounded-full bg-success" />
  {apiError ? "Backend Disconnected" : "Backend Connected"}
</span>
            <button onClick={() => setNight((n) => !n)} aria-label="Toggle day/night" className="icon-btn">{night ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}</button>
            <button onClick={refresh} aria-label="Refresh data" className="icon-btn"><RefreshCw className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`} /></button>
            <div className="relative">
  <button
    onClick={() => setNotifOpen((o) => !o)}
    aria-label="Notifications"
    className="icon-btn relative"
  >
    <Bell className="h-4 w-4" />

    {(dashboardData?.exceptions?.length ?? 0) > 0 && (
      <span className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full bg-destructive" />
    )}
  </button>

  {notifOpen && (
    <div className="absolute right-0 top-full z-40 mt-2 w-80 max-h-96 overflow-y-auto rounded-xl border border-border bg-popover p-3 shadow-panel">

      <p className="mb-2 text-sm font-semibold">
        Delivery Alerts ({dashboardData?.exceptions?.length ?? 0})
      </p>

      {(dashboardData?.exceptions?.length ?? 0) === 0 ? (
        <p className="text-sm text-muted-foreground">
          No delivery exceptions available.
        </p>
      ) : (
        dashboardData?.exceptions?.map((alert) => (
          <div
            key={alert.exception_id}
            className="border-t border-border py-3 text-xs"
          >
            <p className="font-semibold text-destructive">
              {alert.failure_reason.replace(/_/g, " ").toUpperCase()}
            </p>

            <p>Customer: {alert.recipient_name ?? "Unknown"}</p>

            <p>Driver: {alert.driver_name ?? "Unknown"}</p>

            {alert.notes && <p>Notes: {alert.notes}</p>}

            <p>
              Return to hub: {alert.return_to_hub ? "Yes" : "No"}
            </p>

            <p className="mt-1 text-muted-foreground">
              {new Date(alert.created_at).toLocaleString()}
            </p>
          </div>
        ))
      )}
    </div>
  )}
</div>
            <div className="hidden items-center gap-2 pl-2 lg:flex">
              <span className="grid h-9 w-9 place-items-center rounded-full bg-primary/15 font-semibold text-primary">AC</span>
              <span><span className="block text-sm font-semibold leading-tight">Alex Chen</span><span className="block text-xs text-muted-foreground">Operations Manager</span></span>
            </div>
          </div>
        </header>

        {/* MAIN */}
        <main className="relative flex-1 lg:min-h-[calc(100vh-64px)]">
          <div className="relative h-[60vh] lg:absolute lg:inset-0 lg:h-auto" data-scene-ready={ready ? "" : undefined}>
            <WarehouseScene ref={scene} night={night} selected={pick} onPick={setPick} onReady={() => setReady(true)} />
          </div>

          {/* KPIs */}
          <div className="pointer-events-none relative z-10 grid grid-cols-2 gap-3 p-4 lg:absolute lg:left-4 lg:top-4 lg:right-[436px] lg:flex lg:flex-wrap lg:p-0">
            <Kpi
  icon={<Package />}
  label="Active Routes"
  value={dashboardData.stats.active_routes.toLocaleString()}
  sub="Routes currently in progress"
/>
            <Kpi
              icon={<TruckIcon />}
              label="Total vehicles"
              value={dashboardData.stats.total_vehicles.toLocaleString()}
              sub="Registered vehicles"
/>
            <Kpi
              icon={<Clock />}
              label="Out for delivery"
              value={dashboardData.stats.out_for_delivery.toLocaleString()}
              sub="Orders currently out for delivery"
            />

            <Kpi
              icon={<Boxes />}
              label="Total shipments"
              value={dashboardData.stats.total_orders.toLocaleString()}
              sub="Orders in database"
            />

            <Kpi
              icon={<UserRound />}
              label="Available drivers"
              value={dashboardData.stats.available_drivers.toString()}
              sub={`Available out of ${dashboardData.stats.total_drivers}`}
            />

            <Kpi
              icon={<CheckCircle2 />}
              label="Completed deliveries"
              value={dashboardData.stats.delivered_orders.toLocaleString()}
              sub="Successfully delivered"
            />

            <Kpi
              icon={<AlertTriangle />}
              label="Pending orders"
              value={dashboardData.stats.pending_orders.toLocaleString()}
              sub="Currently pending"
            />
          </div>

          {/* Camera controls */}
          <div className="absolute right-4 top-4 z-10 flex flex-col gap-1 rounded-xl border border-border bg-card p-1 shadow-panel lg:right-[372px]">
            <button className="icon-btn" aria-label="Zoom in" onClick={() => scene.current?.zoom(0.8)}><Plus className="h-4 w-4" /></button>
            <button className="icon-btn" aria-label="Zoom out" onClick={() => scene.current?.zoom(1.25)}><Minus className="h-4 w-4" /></button>
            <button className="icon-btn" aria-label="Rotate left" onClick={() => scene.current?.rotate(-0.4)}><RotateCcw className="h-4 w-4" /></button>
            <button className="icon-btn" aria-label="Rotate right" onClick={() => scene.current?.rotate(0.4)}><RotateCw className="h-4 w-4" /></button>
            <button className="icon-btn" aria-label="Reset view" onClick={() => scene.current?.reset()}><Home className="h-4 w-4" /></button>
          </div>

          {/* Selection popup */}
          {(selTruck || selFork) && (
            <div className="panel absolute left-1/2 top-24 z-20 w-72 -translate-x-1/2 p-4 lg:top-32">
              <button onClick={() => setPick(null)} className="absolute right-3 top-3" aria-label="Close"><X className="h-4 w-4 text-muted-foreground" /></button>
              {selTruck && (
                <>
                  <p className="text-xs font-semibold uppercase text-primary">Truck · {selTruck.carrier}</p>
                  <p className="font-display text-lg font-bold">{selTruck.id}</p>
                  <dl className="mt-2 space-y-1 text-sm">
                    <Row k="Shipment" v={`#${selTruck.shipment}`} />
                    <Row k="Destination" v={selTruck.destination} />
                    <Row k="Dock" v={selTruck.bay ?? "Not assigned"} />
                    <Row k="Loaded" v={`${selTruck.loaded}/${selTruck.total} pallets`} />
                    <Row k="ETA" v={selTruck.eta} />
                  </dl>
                  <span className={`chip mt-3 ${statusClass(selTruck.status)}`}>{selTruck.status}</span>
                </>
              )}
              {selFork && (
                <>
                  <p className="text-xs font-semibold uppercase text-warning">Forklift</p>
                  <p className="font-display text-lg font-bold">{selFork.id}</p>
                  <dl className="mt-2 space-y-1 text-sm">
                    <Row k="Operator" v={selFork.operator} />
                    <Row k="Task" v={selFork.task} />
                    <Row k="Battery" v={`${selFork.battery}%`} />
                    <Row k="Progress" v={`${selFork.progress}%`} />
                  </dl>
                  <span className={`chip mt-3 ${selFork.working ? "chip-ok" : "chip-warn"}`}>{selFork.working ? "Working" : "Idle"}</span>
                </>
              )}
            </div>
          )}

          {/* Right panel */}
          <aside className="panel relative z-10 m-4 p-4 lg:absolute lg:bottom-[268px] lg:right-4 lg:top-4 lg:m-0 lg:w-[340px] lg:overflow-y-auto">
            <div className="flex items-start gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary"><Container className="h-5 w-5" /></span>
              <div className="flex-1">
                <p className="text-xs font-semibold uppercase text-primary">Depot · {wh.id}</p>
                <p className="font-display text-lg font-bold leading-tight">{wh.name}</p>
                <p className="text-xs text-muted-foreground">{wh.address}</p>
              </div>
              <button className="icon-btn" aria-label="Center view" onClick={() => scene.current?.reset()}><Crosshair className="h-4 w-4" /></button>
            </div>
            <div className="mt-3 flex items-center gap-2 text-xs">
  <span className={`chip ${dbWarehouse?.is_active ? "chip-ok" : "chip-warn"}`}>
  {dbWarehouse
    ? dbWarehouse.is_active
      ? "Active Warehouse"
      : "Inactive Warehouse"
    : WAITING}
</span>

<span className="text-muted-foreground">
  {dbWarehouse
    ? `${dbWarehouse.total_orders.toLocaleString()} total orders`
    : "Warehouse data unavailable"}
</span>
</div>
            <div className="mt-3 grid grid-cols-2 gap-2">
  <Stat
    label="Total orders"
    value={(dbWarehouse?.total_orders ?? 0).toLocaleString()}
    sub="Assigned to warehouse"
  />

  <Stat
    label="Out for delivery"
    value={(dbWarehouse?.out_for_delivery ?? 0).toLocaleString()}
    sub="Current orders"
  />

  <Stat
    label="Delivered orders"
    value={(dbWarehouse?.delivered_orders ?? 0).toLocaleString()}
    sub="Successfully delivered"
  />

  <Stat
    label="Warehouse status"
    value={dbWarehouse?.is_active ? "Active" : "Closed"}
    sub="Database status"
  />
</div>
            <div className="mt-4 flex items-center justify-between text-sm font-semibold">
  <span>Inventory</span>
</div>

<div className="mt-2 rounded-lg bg-muted p-4 text-center">
  <Package className="mx-auto h-7 w-7 text-muted-foreground" />

  <p className="mt-2 text-sm font-semibold">
    Inventory data unavailable
  </p>

  <p className="mt-1 text-xs text-muted-foreground">
    Inventory management is not currently integrated.
  </p>
</div>
            <div className="mt-4 flex justify-between text-sm font-semibold"><span>Forklift fleet</span><span className="text-xs font-normal text-muted-foreground">0/2 working</span></div>
            {forklifts.map((f) => (
              <button key={f.id} onClick={() => setPick({ type: "forklift", id: f.id })} className="mt-2 flex w-full items-center gap-2 text-left text-xs">
                <b className="w-10">{f.id}</b><span className="flex-1 truncate text-muted-foreground">{f.task}</span>
                <span className="h-1.5 w-14 overflow-hidden rounded-full bg-muted"><span className="block h-full bg-success" style={{ width: `${f.progress}%` }} /></span>
                <span className="w-8 text-right">{f.progress}%</span>
              </button>
            ))}
          </aside>

          {/* Bottom row */}
          <div className="relative z-10 flex flex-col gap-4 p-4 pt-0 lg:absolute lg:inset-x-4 lg:bottom-4 lg:flex-row lg:items-end lg:p-0">
            
<section className="panel flex-1 p-4 lg:max-w-3xl">
  <div className="flex flex-wrap items-center justify-between gap-3">
    <p className="flex items-center gap-2 font-display font-bold">
      <TruckIcon className="h-5 w-5 text-primary" />
      Shipment Tracking
    </p>

    <select
      value={selectedShipment?.order_id ?? ""}
      onChange={(e) => setSelectedShipmentId(e.target.value)}
      className="max-w-[220px] rounded-lg border border-border bg-background p-2 text-xs"
    >
      {dashboardData.shipments.map((s) => (
        <option key={s.order_id} value={s.order_id}>
          {s.merchant_order_ref || s.order_id.slice(0, 8)}
          {" · "}
          {s.status}
        </option>
      ))}
    </select>
  </div>

  {selectedShipment ? (
    <>
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 text-xs">
        <div>
          <p className="font-semibold">
            {selectedShipment.recipient_name || "Customer"}
          </p>
          <p className="text-muted-foreground">
            {selectedShipment.locality || "Location unavailable"}
          </p>
        </div>

        <span className="chip chip-info">
          {selectedShipment.status.replaceAll("_", " ")}
        </span>
      </div>

      <p className="mt-2 break-all text-[10px] text-muted-foreground">
        Order ID: {selectedShipment.order_id}
      </p>

      <div className="mt-4 max-h-44 space-y-3 overflow-y-auto">
        <p className="text-xs font-semibold">Actual order history</p>

        {selectedShipment.events.length > 0 ? (
          selectedShipment.events.map((event, index) => (
            <div
              key={`${event.occurred_at}-${index}`}
              className="flex items-start gap-3"
            >
              <span className="mt-1 h-2.5 w-2.5 shrink-0 rounded-full bg-primary" />

              <div className="min-w-0 flex-1">
                <p className="text-xs font-semibold capitalize">
                  {event.to_status.replaceAll("_", " ")}
                </p>

                <p className="text-[10px] text-muted-foreground">
                  {event.from_status
                    ? `Previous: ${event.from_status.replaceAll("_", " ")}`
                    : "Order created"}
                </p>

                <p className="text-[10px] text-muted-foreground">
                  {new Date(event.occurred_at).toLocaleString()}
                </p>
              </div>
            </div>
          ))
        ) : (
          <p className="text-xs text-muted-foreground">
            No status events recorded for this order.
          </p>
        )}
      </div>

      {selectedShipment.stop_status && (
        <p className="mt-3 text-xs text-muted-foreground">
          Route stop status: {selectedShipment.stop_status}
        </p>
      )}
    </>
  ) : (
    <div className="py-8 text-center">
      <Package className="mx-auto h-8 w-8 text-muted-foreground" />
      <p className="mt-2 text-sm font-semibold">No shipment records</p>
      <p className="text-xs text-muted-foreground">
        No orders are currently available from the backend.
      </p>
    </div>
  )}
</section>


            <section className="panel p-4 lg:ml-auto lg:w-[340px]">
              <div className="flex flex-wrap items-center gap-1 text-xs">
  {(["drivers", "routes", "docks", "forklifts", "trucks"] as const).map((t) => {
    const count =
      t === "drivers" ? dashboardData.drivers.length :
      t === "routes" ? dashboardData.routes.length :
      t === "docks" ? 2 :
      t === "forklifts" ? forklifts.length :
      trucks.length;

    return (
      <button
        key={t}
        onClick={() => setTab(t)}
        className={`whitespace-nowrap rounded-lg px-2 py-1 font-semibold capitalize ${
          tab === t
            ? "bg-primary/15 text-primary"
            : "text-muted-foreground hover:bg-muted"
        }`}
      >
        {t} {count}
      </button>
    );
  })}
</div>
              <ul className="mt-2 max-h-64 divide-y divide-border overflow-y-auto text-sm">

  {/* DRIVERS */}
  {tab === "drivers" && (
  <>
    <li className="py-2">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs font-semibold">
          Filter Drivers
        </span>

        <select
          value={driverFilter}
          onChange={(e) => setDriverFilter(e.target.value)}
          disabled={updatingDriver !== null}
          className="rounded-md border border-border bg-background px-2 py-1 text-xs"
        >
          <option value="all">All Drivers</option>
          <option value="available">Available</option>
          <option value="on_route">On Route</option>
          <option value="offline">Offline</option>
          <option value="pending">Pending</option>
          <option value="rejected">Rejected</option>
        </select>
      </div>
    </li>

    {driverLoading && (
      <li className="py-3 text-center text-xs text-muted-foreground">
        Loading drivers...
      </li>
    )}

    {driverError && (
      <li className="py-2 text-xs text-red-500">
        {driverError}
      </li>
    )}

    {!driverLoading && driverRecords.map((driver) => {
      const liveDriver = dashboardData.drivers.find(
        (d) => d.driver_id === driver.user_id
      );

      const latitude =
        liveDriver?.latitude ?? liveDriver?.lat;

      const longitude =
        liveDriver?.longitude ?? liveDriver?.lng;

      const hasLocation =
        latitude != null && longitude != null;

      return (
        <li key={driver.user_id} className="py-2">
          <div className="flex items-center gap-2">
            <UserRound className="h-4 w-4 text-primary" />

            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-semibold">
                {liveDriver?.driver_name || driver.user_id}
              </p>

              <p className="truncate text-[10px] text-muted-foreground">
                {driver.vehicle_id
                  ? `Vehicle: ${driver.vehicle_id}`
                  : "No vehicle assigned"}
              </p>
            </div>

            <span className={`chip ${
              driver.status === "available"
                ? "chip-ok"
                : driver.status === "offline" ||
                  driver.status === "rejected"
                  ? "chip-bad"
                  : "chip-info"
            }`}>
              {driver.status}
            </span>
          </div>

          <p className="mt-1 pl-6 text-[10px] text-muted-foreground">
            {hasLocation
              ? `Location: ${latitude}, ${longitude}`
              : "No live location available"}
          </p>
{hasLocation && (
  <div className="mt-1 space-y-1 pl-6 text-[10px] text-muted-foreground">
    <p>
      Speed: {liveDriver?.speed ?? "Unavailable"}
    </p>

    <p>
      Last GPS update:{" "}
      {liveDriver?.timestamp
        ? new Date(liveDriver.timestamp).toLocaleString()
        : "Unavailable"}
    </p>
  </div>
)}
          {liveDriver?.stale && (
            <p className="pl-6 text-[10px] text-amber-500">
              Location data is stale
            </p>
          )}

          <div className="mt-2 flex items-center gap-2 pl-6">
            <span className="text-[10px] text-muted-foreground">
              Update Status:
            </span>

            <select
              value={driver.status}
              disabled={
                updatingDriver !== null ||
                driver.status === "on_route"
              }
              onChange={(e) =>
                handleDriverStatusUpdate(
                  driver.user_id,
                  e.target.value
                )
              }
              className="rounded-md border border-border bg-background px-2 py-1 text-[10px]"
            >
              <option value="available">Available</option>
              <option value="on_route" disabled>On Route</option>
              <option value="offline">Offline</option>
              <option value="pending">Pending</option>
              <option value="rejected">Rejected</option>
            </select>

            {updatingDriver === driver.user_id && (
              <span className="text-[10px] text-primary">
                Updating...
              </span>
            )}
          </div>
        </li>
      );
    })}

    {!driverLoading &&
      !driverError &&
      driverRecords.length === 0 && (
        <li className="py-4 text-center text-xs text-muted-foreground">
          No drivers found.
        </li>
      )}
  </>
)}

  {/* ROUTES */}
  {tab === "routes" && (
  <>
    {dashboardData.routes.map((route) => {
      const assignedDriver = dashboardData.drivers.find(
        (driver) => driver.driver_id === route.driver_id
      );

      return (
        <li key={route.route_id} className="py-2">
          <div className="flex items-center gap-2">
            <TruckIcon className="h-4 w-4 text-primary" />

            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-semibold">
                Route {route.route_id.slice(0, 8)}
              </p>

              <p className="text-[10px] text-muted-foreground">
                {route.total_stops ?? route.stops?.length ?? 0} stops
                {" · "}
                {route.total_distance_m != null
                  ? `${(route.total_distance_m / 1000).toFixed(1)} km`
                  : "Distance unavailable"}
              </p>
            </div>

            <span className="chip chip-info">
              {route.status || "Unknown"}
            </span>
          </div>

          <div className="mt-2 space-y-1 pl-6 text-[10px] text-muted-foreground">
            <p>
              <b>Driver:</b>{" "}
              {assignedDriver?.driver_name ||
                route.driver_id ||
                "Not assigned"}
            </p>

            <p className="break-all">
              <b>Vehicle:</b>{" "}
              {route.vehicle_id || "Not assigned"}
            </p>

            <p>
              <b>Assigned orders:</b>{" "}
              {route.total_stops ?? route.stops?.length ?? 0}
            </p>

{route.stops && route.stops.length > 0 && (
  <details className="mt-2 rounded-md bg-muted p-2">
    <summary className="cursor-pointer text-xs font-semibold">
      View Assigned Orders
    </summary>

    {route.stops.map((stop, index) => (
      <div
        key={stop.stop_id ?? stop.order_id}
        className="mt-2 border-t pt-2 text-xs"
      >
        <p className="font-semibold">
          Stop {stop.sequence ?? index + 1}:{" "}
          {stop.recipient_name ?? "Unknown recipient"}
        </p>

        <p className="text-muted-foreground">
          Order status: {stop.order_status ?? "Unavailable"}
        </p>

        <p className="text-muted-foreground">
          Stop status: {stop.stop_status ?? stop.status ?? "Unavailable"}
        </p>
      </div>
    ))}
  </details>
)}
{route.status === "in_progress" && (
  <button
    className="mt-2 w-full rounded-md border border-red-500 px-3 py-2 text-xs font-semibold text-red-500 hover:bg-red-50"
    onClick={async (e) => {
      const button = e.currentTarget;

      if (!window.confirm("Request rescue for this route?")) {
        return;
      }

      button.disabled = true;

      try {
        await requestRescue(route.route_id);
        alert("Rescue request published successfully!");
      } catch (error) {
        alert(
          error instanceof Error
            ? error.message
            : "Rescue request failed"
        );
      } finally {
        button.disabled = false;
      }
    }}
  >
    Request Rescue
  </button>
)}
            
          </div>
        </li>
      );
    })}

    {dashboardData.routes.length === 0 && (
      <li className="py-4 text-center text-xs text-muted-foreground">
        No routes found.
      </li>
    )}
  </>
)}
  {/* EXISTING DOCKS */}
  {tab === "docks" && (
    <>
      <DockRow
        bay="Bay 1"
        truck="TRK-2051 · LastMileDelivery"
        status="Waiting"
        progress={0}
        extra="0%"
        onClick={() => setPick({ type: "truck", id: "TRK-2051" })}
      />
      <DockRow bay="Bay 2" truck="No truck assigned" status="Waiting" />
      <DockRow
        bay="Inbound"
        truck="TRK-2287 · Bluepeak"
        status="Waiting"
        extra="—"
        onClick={() => setPick({ type: "truck", id: "TRK-2287" })}
      />
    </>
  )}

  {/* EXISTING FORKLIFTS */}
  {tab === "forklifts" && forklifts.map((f) => (
    <li key={f.id}>
      <button
        onClick={() => setPick({ type: "forklift", id: f.id })}
        className="flex w-full items-center gap-2 py-2 text-left"
      >
        <ForkliftIcon className="h-4 w-4 text-warning" />
        <b>{f.id}</b>
        <span className="flex-1 truncate text-xs text-muted-foreground">
          {f.operator}
        </span>
        <span className={`chip ${f.working ? "chip-ok" : "chip-warn"}`}>
          {f.working ? "Working" : "Idle"}
        </span>
      </button>
    </li>
  ))}

  {/* EXISTING TRUCKS */}
  {tab === "trucks" && trucks.map((t) => (
    <li key={t.id}>
      <button
        onClick={() => setPick({ type: "truck", id: t.id })}
        className="flex w-full items-center gap-2 py-2 text-left"
      >
        <TruckIcon className="h-4 w-4 text-primary" />
        <b>{t.id}</b>
        <span className="flex-1 truncate text-xs text-muted-foreground">
          {t.destination}
        </span>
        <span className={`chip ${statusClass(t.status)}`}>
          {t.status}
        </span>
      </button>
    </li>
  ))}

</ul>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}

function Kpi({ icon, label, value, delta, sub }: { icon: React.ReactNode; label: string; value: string; delta?: string; sub: string }) {
  return (
    <div className="panel pointer-events-auto flex items-center gap-3 px-3 py-2.5 lg:min-w-[180px]">
      <span className="grid h-10 w-10 place-items-center rounded-lg bg-primary/15 text-primary [&>svg]:h-5 [&>svg]:w-5">{icon}</span>
      <div>
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className="flex items-baseline gap-1.5 font-display text-xl font-bold leading-tight">{value}{delta && <span className="flex items-center text-xs font-semibold text-success"><ArrowUp className="h-3 w-3" />{delta}</span>}</p>
        <p className="text-[10px] text-muted-foreground">{sub}</p>
      </div>
    </div>
  );
}

function Stat({ label, value, sub, pct, good }: { label: string; value: string; sub: string; pct?: number; good?: boolean }) {
  return (
    <div className="rounded-lg bg-muted p-2">
      <p className="text-[11px] text-muted-foreground">{label}</p>
      <p className="font-display font-bold">{value} <span className="text-xs font-normal text-muted-foreground">{sub}</span></p>
      {pct !== undefined && <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-border"><span className={`block h-full ${good ? "bg-success" : "bg-primary"}`} style={{ width: `${pct * 100}%` }} /></span>}
    </div>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return <div className="flex justify-between gap-2"><dt className="text-muted-foreground">{k}</dt><dd className="text-right font-medium">{v}</dd></div>;
}

function DockRow({ bay, truck, status, progress, extra, onClick }: { bay: string; truck: string; status: string; progress?: number; extra?: string; onClick?: () => void }) {
  return (
    <li><button onClick={onClick} disabled={!onClick} className="flex w-full items-center gap-2 py-2 text-left">
      <span className="w-14"><b className="block text-xs">{bay}</b><span className="text-[10px] text-muted-foreground">WH-01</span></span>
      <span className="flex-1 truncate text-xs">{truck}</span>
      <span className={`chip ${statusClass(status)}`}>{status}</span>
      {progress !== undefined ? (
        <span className="w-10 text-[10px]"><span className="block h-1 overflow-hidden rounded-full bg-muted"><span className="block h-full bg-success" style={{ width: `${progress * 100}%` }} /></span>{extra}</span>
      ) : <span className="w-10 text-[10px] text-muted-foreground">{extra}</span>}
    </button></li>
  );
}
