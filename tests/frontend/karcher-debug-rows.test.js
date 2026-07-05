import { describe, it, expect } from "vitest";
import { buildDebugRows } from "../../custom_components/karcher_home_robots/www/karcher-vacuum-card.js";

const baseArgs = {
  version: "1.31.0",
  hass: { config: { version: "2026.5.4" } },
  config: { vacuum_entity: "vacuum.karcher_rcv5" },
  vacState: { state: "cleaning", last_updated: "2026-07-04T12:04:31+00:00" },
  imgSize: { width: 200, height: 160 },
  mapLoaded: true,
  offline: false,
};

const rowMap = (rows) => Object.fromEntries(rows.map((r) => [r.label, r.value]));

describe("buildDebugRows", () => {
  it("returns the curated fields in order", () => {
    const rows = buildDebugRows(baseArgs);
    expect(rows.map((r) => r.label)).toEqual([
      "card", "HA", "entity", "state", "map", "conn", "updated",
    ]);
  });

  it("passes through version, HA version, entity, and state", () => {
    const m = rowMap(buildDebugRows(baseArgs));
    expect(m.card).toBe("1.31.0");
    expect(m.HA).toBe("2026.5.4");
    expect(m.entity).toBe("vacuum.karcher_rcv5");
    expect(m.state).toBe("cleaning");
  });

  it("formats map dimensions when loaded", () => {
    expect(rowMap(buildDebugRows(baseArgs)).map).toBe("200×160");
  });

  it("shows a dash for the map when not loaded", () => {
    expect(rowMap(buildDebugRows({ ...baseArgs, mapLoaded: false })).map).toBe("—");
  });

  it("says loaded without dimensions when size is missing", () => {
    expect(rowMap(buildDebugRows({ ...baseArgs, imgSize: undefined })).map).toBe("loaded");
  });

  it("reflects offline state", () => {
    expect(rowMap(buildDebugRows({ ...baseArgs, offline: true })).conn).toBe("offline");
    expect(rowMap(buildDebugRows(baseArgs)).conn).toBe("online");
  });

  it("collapses missing inputs to a dash", () => {
    const m = rowMap(buildDebugRows({}));
    expect(m.card).toBe("—");
    expect(m.HA).toBe("—");
    expect(m.entity).toBe("—");
    expect(m.state).toBe("—");
    expect(m.updated).toBe("—");
  });

  it("never leaks device_id, serial, or raw attributes", () => {
    const vacState = {
      state: "cleaning",
      last_updated: "2026-07-04T12:04:31+00:00",
      attributes: {
        serial_number: "SN-SECRET-123",
        room_map: { 1: { name: "Kitchen" } },
        friendly_name: "Kärcher RCV5",
      },
    };
    const hass = {
      config: { version: "2026.5.4" },
      entities: { "vacuum.karcher_rcv5": { device_id: "dev-secret-xyz" } },
    };
    const serialized = JSON.stringify(buildDebugRows({ ...baseArgs, hass, vacState }));
    expect(serialized).not.toContain("SN-SECRET-123");
    expect(serialized).not.toContain("dev-secret-xyz");
    expect(serialized).not.toContain("room_map");
  });
});
