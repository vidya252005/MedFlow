const TOKEN_KEY = "medflow_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, headers });
  if (response.status === 401) {
    clearToken();
    throw new Error("unauthorized");
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || response.statusText);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: (username: string, password: string) =>
    request<{ access_token: string; role: string }>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password }),
    }),
  overview: () => request<Overview>("/api/v1/overview"),
  events: () => request<{ items: EventRow[] }>("/api/v1/events"),
  alerts: (status?: string) =>
    request<{ items: AlertRow[] }>(`/api/v1/alerts${status ? `?status=${status}` : ""}`),
  ack: (id: string) => request(`/api/v1/alerts/${id}/acknowledge`, { method: "POST" }),
  resolve: (id: string) => request(`/api/v1/alerts/${id}/resolve`, { method: "POST" }),
  models: () => request<ModelsResponse>("/api/v1/models"),
  dlq: () => request<{ items: DlqRow[] }>("/api/v1/dlq"),
  replay: (id: string) => request(`/api/v1/dlq/${id}/replay`, { method: "POST" }),
  patients: () => request<{ items: Patient[] }>("/api/v1/patients"),
  insights: (id: string) => request<Insights>(`/api/v1/patients/${id}/insights`),
  scenarios: () => request<{ items: Scenario[] }>("/api/v1/simulator/scenarios"),
  runScenario: (name: string, count = 40, patientId?: string) =>
    request<{ accepted: number }>(
      `/api/v1/simulator/scenarios/${name}?count=${count}${patientId ? `&patient_id=${patientId}` : ""}`,
      { method: "POST" },
    ),
  audit: () => request<{ items: AuditRow[] }>("/api/v1/audit"),
};

export type Overview = {
  events_per_min: number;
  active_patients: number;
  open_alerts: number;
  model_success_rate: number;
  consumer_lag: number;
  p95_processing_latency_ms: number | null;
  alerts_by_severity: Record<string, number>;
};

export type EventRow = {
  event_id: string;
  event_type: string;
  patient_id?: string;
  status: string;
  timestamp: string;
  trace_id: string;
};

export type AlertRow = {
  id: string;
  patient_id?: string;
  event_id: string;
  alert_type: string;
  severity: string;
  status: string;
  message: string;
  explanation?: Record<string, unknown>;
  created_at: string;
};

export type Patient = { id: string; display_name: string; ward_id: string };
export type Scenario = { name: string; description: string };
export type DlqRow = {
  id: string;
  event_id?: string;
  failure_code: string;
  error: string;
  replayed: boolean;
  created_at: string;
};
export type AuditRow = {
  id: number;
  actor?: string;
  action: string;
  resource_type?: string;
  created_at: string;
};
export type Insights = {
  patient: { id: string; display_name: string; ward_id?: string };
  events: EventRow[];
  alerts: AlertRow[];
  decisions: Array<{
    id: string;
    severity: string;
    action: string;
    decision_score: number;
    triggered_rules: string[];
    explanation?: Record<string, unknown>;
  }>;
};
export type ModelsResponse = {
  stats: Array<{
    model_name: string;
    model_version: string;
    p95_ms: number;
    success_rate: number;
    count: number;
  }>;
  registry: Record<string, { version: string; timeout_ms: number; enabled: boolean; shadow: boolean; fallback?: string }>;
  circuits: Record<string, Record<string, string>>;
};
