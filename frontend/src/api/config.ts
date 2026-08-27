const fallbackApiUrl = import.meta.env.DEV ? "http://127.0.0.1:8000" : "";

function normalizeApiUrl(value: string | undefined): string {
  const configured = value?.trim() || fallbackApiUrl;
  return configured.replace(/\/+$/, "");
}

export const apiConfig = {
  baseUrl: normalizeApiUrl(import.meta.env.VITE_API_URL),
};
