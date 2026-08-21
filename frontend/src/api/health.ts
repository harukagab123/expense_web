import { apiConfig } from "./config";

export type HealthResponse = {
  status: "ok" | "error";
  database: "connected" | "unavailable";
};

export async function getHealth(): Promise<HealthResponse> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), 5000);

  try {
    const response = await fetch(`${apiConfig.baseUrl}/api/health`, {
      signal: controller.signal,
      headers: {
        Accept: "application/json",
      },
    });

    const data = (await response.json()) as HealthResponse;

    if (!response.ok) {
      return {
        status: "error",
        database: data.database ?? "unavailable",
      };
    }

    return data;
  } finally {
    window.clearTimeout(timeout);
  }
}
