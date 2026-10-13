export type Role = "admin" | "receptionist" | "staff";
export type User = { id: string; email: string; display_name: string; role: Role };
export type Department = {
  id: string;
  code: string;
  name: string;
  available_staff: number;
  default_service_minutes: number;
};
export type Ticket = {
  id: string;
  patient_reference: string;
  display_name: string | null;
  department_id: string;
  department: string;
  token: string;
  token_number: number;
  appointment_type: "walk-in" | "appointment";
  priority: string;
  status: string;
  arrival_at: string;
  service_started_at: string | null;
  service_completed_at: string | null;
  patients_ahead: number;
  actual_wait_minutes: number | null;
};
export type Overview = {
  total_registered: number;
  waiting: number;
  in_service: number;
  completed: number;
  actual_average_wait_minutes: number | null;
  departments: Array<{
    department_id: string;
    department: string;
    waiting: number;
    in_service: number;
    available_staff: number;
  }>;
  data_label: string;
};
export type Prediction = {
  id: string;
  ticket_id: string;
  predicted_minutes: number | null;
  lower_minutes: number | null;
  upper_minutes: number | null;
  model: string;
  predicted_at: string;
  uncertainty_note: string;
  inputs: Record<string, number | boolean>;
  factors: string[];
};
export type SimulationResult = {
  id: string;
  label: string;
  seed: number;
  arrivals_shared: boolean;
  baseline: SimulationScenario;
  alternative: SimulationScenario;
  difference: { average_wait_minutes: number | null; p90_wait_minutes: number | null };
};
export type SimulationScenario = {
  patients: number;
  average_wait_minutes: number | null;
  p90_wait_minutes: number | null;
  maximum_queue: number;
  throughput_per_hour: number;
  staff_utilization_percent: number;
};
