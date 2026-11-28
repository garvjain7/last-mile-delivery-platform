import { createFileRoute } from "@tanstack/react-router";
import { Dashboard } from "@/components/wt/Dashboard";

export const Route = createFileRoute("/")({
  ssr: false,
  head: () => ({
    meta: [
      { title: "LastMileDelivery — Warehouse & Last-Mile Control Tower" },
      { name: "description", content: "Interactive 3D warehouse control tower: inventory, docks, forklifts and shipment tracking." },
      { property: "og:title", content: "LastMileDelivery — Warehouse Control Tower" },
      { property: "og:description", content: "Live 3D view of inventory, docks, forklifts and last-mile shipments." },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
    ],
  }),
  component: Dashboard,
});
