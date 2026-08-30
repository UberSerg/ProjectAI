import { describe, expect, it } from "vitest";
import {
  overviewHealthBadgeStatus,
  overviewHealthKind,
  overviewHealthTitle,
  resolveServiceStatus,
} from "./health";

describe("health mapping", () => {
  it("maps core_database/memory_database to ok", () => {
    const services = { core_database: "ok", memory_database: "ok" };
    expect(resolveServiceStatus(services, "core_database")).toBe("ok");
    expect(resolveServiceStatus(services, "memory_database")).toBe("ok");
  });

  it("accepts legacy core_db aliases", () => {
    expect(resolveServiceStatus({ core_db: "ok" }, "core_database")).toBe("ok");
    expect(resolveServiceStatus({ memory_db: "ok" }, "memory_database")).toBe("ok");
  });

  it("marks missing scheduler as not_monitored", () => {
    expect(resolveServiceStatus({ backend: "ok" }, "scheduler")).toBe("not_monitored");
  });

  it("shows healthy overview when mandatory services are ok", () => {
    const health = {
      status: "ok" as const,
      services: {
        backend: "ok" as const,
        core_database: "ok" as const,
        memory_database: "ok" as const,
        redis: "ok" as const,
        worker: "ok" as const,
      },
    };
    expect(overviewHealthKind(health)).toBe("ok");
    expect(overviewHealthTitle(health)).toBe("Система работает нормально");
    expect(overviewHealthBadgeStatus(health)).toBe("ok");
  });

  it("does not treat missing scheduler as system error", () => {
    const health = {
      status: "ok" as const,
      services: {
        backend: "ok" as const,
        core_database: "ok" as const,
        memory_database: "ok" as const,
        redis: "ok" as const,
        worker: "ok" as const,
      },
    };
    expect(resolveServiceStatus(health.services, "scheduler")).toBe("not_monitored");
    expect(overviewHealthTitle(health)).toBe("Система работает нормально");
  });
});
