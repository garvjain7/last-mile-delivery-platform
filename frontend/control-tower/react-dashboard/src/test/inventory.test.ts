import { describe, it, expect } from "vitest";
import { stockStatus, filterInventory, baseInventory } from "@/lib/warehouse-data";
describe("inventory rules", () => {
  it("flags low stock below minimum", () => expect(stockStatus({ qty: 212, min: 300 })).toBe("Low Stock"));
  it("flags zero as out of stock", () => expect(stockStatus({ qty: 0, min: 40 })).toBe("Out of Stock"));
  it("search matches by name", () => expect(filterInventory(baseInventory, "tape").map((i) => i.name)).toEqual(["Packing Tape"]));
});
