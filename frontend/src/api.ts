import type { Department, Overview, Prediction, RegistrationSession, SimulationResult, Ticket, User } from "./types";

const base = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const TOKEN_KEY = "flowcare-token";

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY);
  const response = await fetch(`${base}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string | Array<{ msg: string }> } | null;
    let detailMsg: string | undefined;
    if (typeof body?.detail === "string") {
      detailMsg = body.detail;
    } else if (Array.isArray(body?.detail)) {
      detailMsg = body.detail.map((item) => item.msg || JSON.stringify(item)).join(". ");
    }
    throw new ApiError(detailMsg ?? `Request failed (${response.status}).`, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  login: async (email: string, password: string) => {
    const result = await request<{ access_token: string; user: User }>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    localStorage.setItem(TOKEN_KEY, result.access_token);
    return result.user;
  },
  signup: async (payload: { email: string; password: string; display_name: string }) => {
    const result = await request<{ access_token: string; user: User }>("/api/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    localStorage.setItem(TOKEN_KEY, result.access_token);
    return result.user;
  },
  me: () => request<User>("/api/auth/me"),
  logout: () => localStorage.removeItem(TOKEN_KEY),
  departments: () => request<Department[]>("/api/departments"),
  overview: () => request<Overview>("/api/analytics/overview"),
  queue: (departmentId?: string) =>
    request<Ticket[]>(`/api/queue/current${departmentId ? `?department_id=${encodeURIComponent(departmentId)}` : ""}`),
  register: (payload: {
    department_id: string;
    appointment_type: string;
    display_name?: string;
    priority: string;
  }) =>
    request<Ticket>("/api/patients", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateStatus: (ticketId: string, status: string) =>
    request<Ticket>(`/api/queue/tickets/${ticketId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    }),
  predict: (ticketId: string) =>
    request<Prediction>(`/api/predictions/wait-time?ticket_id=${encodeURIComponent(ticketId)}`, {
      method: "POST",
    }),
  simulate: (payload: {
    patients: number;
    arrival_rate_per_hour: number;
    service_mean_minutes: number;
    baseline_doctors: number;
    alternative_doctors: number;
    seed: number;
  }) =>
    request<SimulationResult>("/api/simulations/compare", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  trends: () => request<Array<{ hour: string; registered: number }>>("/api/analytics/trends"),
  bottlenecks: () =>
    request<Array<{ department: string; severity: string; waiting: number; message: string }>>(
      "/api/analytics/bottlenecks",
    ),
  staff: () =>
    request<Array<{ id: string; email: string; display_name: string; role: string; active: boolean }>>(
      "/api/staff",
    ),
  createDepartment: (payload: {
    code: string;
    name: string;
    is_active?: boolean;
    description?: string | null;
    available_staff: number;
    default_service_minutes: number;
  }) =>
    request<Department>("/api/departments", { method: "POST", body: JSON.stringify(payload) }),
  updateDepartment: (departmentId: string, payload: {
    code: string;
    name: string;
    is_active?: boolean;
    description?: string | null;
    available_staff: number;
    default_service_minutes: number;
  }) =>
    request<Department>(`/api/departments/${encodeURIComponent(departmentId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  bookSession: (sessionId: string, payload: { patient_name?: string; idempotency_key?: string }) =>
    request<{ id: string; booking_reference: string; session_id: string; channel: string; status: string; patient_name: string | null; created_at: string; confirmed_at: string; cancelled_at: string | null; cancellation_reason: string | null; idempotency_key: string | null }>(`/api/registration/sessions/${encodeURIComponent(sessionId)}/online-bookings`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listRegistrationSessions: () => request<RegistrationSession[]>("/api/registration/sessions"),
  createRegistrationSession: (payload: {
    department_id?: string | null;
    session_name: string;
    status?: "DRAFT" | "PUBLISHED" | "CANCELLED" | "COMPLETED";
    description?: string | null;
    session_date: string;
    total_capacity: number;
    initial_online_capacity: number;
    initial_physical_capacity: number;
    auto_reallocate_online?: boolean;
    session_start_local: string;
    session_end_local: string;
    online_open_local: string;
    online_close_local: string;
    physical_open_local: string;
    physical_close_local: string;
    timezone_name?: string;
  }) =>
    request<RegistrationSession>("/api/admin/registration/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  updateRegistrationSession: (sessionId: string, payload: Partial<{
    department_id?: string | null;
    session_name: string;
    status: "DRAFT" | "PUBLISHED" | "CANCELLED" | "COMPLETED";
    description: string | null;
    total_capacity: number;
    initial_online_capacity: number;
    initial_physical_capacity: number;
    auto_reallocate_online: boolean;
    session_start_local: string;
    session_end_local: string;
    online_open_local: string;
    online_close_local: string;
    physical_open_local: string;
    physical_close_local: string;
    timezone_name: string;
  }>) =>
    request<RegistrationSession>(`/api/admin/registration/sessions/${encodeURIComponent(sessionId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  createStaff: (payload: { email: string; display_name: string; role: string; password: string }) =>
    request<{ id: string }>("/api/staff", { method: "POST", body: JSON.stringify(payload) }),
  updateAvailability: (departmentId: string, available_staff: number) =>
    request<{ department_id: string; available_staff: number }>(`/api/staff/${departmentId}/availability`, {
      method: "PATCH",
      body: JSON.stringify({ available_staff }),
    }),
  auditLogs: () =>
    request<Array<{ id: string; user_id: string | null; action: string; resource_type: string; resource_id: string | null; occurred_at: string }>>(
      "/api/audit-logs",
    ),
};
