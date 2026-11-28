export const BACKEND_CONNECTED = false;
export const WAITING = "Waiting for Backend Connection";

export type StockStatus = "In Stock" | "Low Stock" | "Out of Stock";

export interface InventoryItem {
  id: string;
  name: string;
  qty: number;
  min: number;
  kind: "box" | "container" | "helmet" | "tape" | "pallet" | "wrap";
}

export const stockStatus = (i: Pick<InventoryItem, "qty" | "min">): StockStatus =>
  i.qty === 0 ? "Out of Stock" : i.qty < i.min ? "Low Stock" : "In Stock";

export const filterInventory = (items: InventoryItem[], q: string) => {
  const s = q.trim().toLowerCase();
  return s ? items.filter((i) => i.name.toLowerCase().includes(s) || i.id.toLowerCase().includes(s)) : items;
};

export interface Warehouse {
  id: string;
  name: string;
  address: string;
  capacity: number;
  stock: number;
  bays: number;
  baysBusy: number;
  outbound: number;
  putaways: number;
}

export const warehouses: Warehouse[] = [
  { id: "WH-01", name: "Riverside Hub", address: "12 Riverside Dr, Newark NJ", capacity: 1800, stock: 0, bays: 0, baysBusy: 0, outbound: 0, putaways: 0 },
  { id: "WH-02", name: "Harbor Point", address: "88 Port Ave, Elizabeth NJ", capacity: 2400, stock: 0, bays: 0, baysBusy: 0, outbound: 0, putaways: 0 },
  { id: "WH-03", name: "Northgate DC", address: "401 Route 17, Paramus NJ", capacity: 1200, stock: 0, bays: 0, baysBusy: 0, outbound: 0, putaways: 0 },
];

export const baseInventory: InventoryItem[] = [
  { id: "SKU-1001", name: "Cardboard Box (M)", qty: 0, min: 500, kind: "box" },
  { id: "SKU-1002", name: "Plastic Container", qty: 0, min: 150, kind: "container" },
  { id: "SKU-1003", name: "Safety Helmet", qty: 0, min: 300, kind: "helmet" },
  { id: "SKU-1004", name: "Packing Tape", qty: 0, min: 1000, kind: "tape" },
  { id: "SKU-1005", name: "Wooden Pallet", qty: 0, min: 120, kind: "pallet" },
  { id: "SKU-1006", name: "Stretch Wrap Roll", qty: 0, min: 40, kind: "wrap" },
];

export interface Truck {
  id: string;
  carrier: string;
  shipment: string;
  destination: string;
  status: "Loading" | "En route" | "Departed" | "Waiting";
  bay: string | null;
  loaded: number;
  total: number;
  eta: string;
}

export const trucks: Truck[] = [
  { id: "TRK-2051", carrier: "LastMileDelivery", shipment: "SHP-78442", destination: "Philadelphia, PA", status: "Waiting", bay: null, loaded: 0, total: 0, eta: "—" },
  { id: "TRK-2287", carrier: "Bluepeak", shipment: "SHP-78451", destination: "Trenton, NJ", status: "Waiting", bay: null, loaded: 0, total: 0, eta: "—" },
];

export interface Forklift {
  id: string;
  operator: string;
  task: string;
  battery: number;
  progress: number;
  working: boolean;
}

export const forklifts: Forklift[] = [
  { id: "FL-01", operator: "Maria Gomez", task: WAITING, battery: 0, progress: 0, working: false },
  { id: "FL-02", operator: "Dev Patel", task: WAITING, battery: 0, progress: 0, working: false },
];

export const shipmentSteps = [
  { label: "Order Confirmed", time: "—" },
  { label: "Picked", time: "—" },
  { label: "Loading", time: "—" },
  { label: "In Transit", time: "—" },
  { label: "Delivered", time: "—" },
];
