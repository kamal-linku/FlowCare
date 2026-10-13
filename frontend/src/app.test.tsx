import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { api } from "./api";
import App from "./App";

vi.mock("./api", async (importOriginal) => {
  const original = await importOriginal<typeof import("./api")>();
  return {
    ...original,
    api: {
      ...original.api,
      me: vi.fn(),
      login: vi.fn(),
      signup: vi.fn(),
      overview: vi.fn(),
    },
  };
});

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.clearAllMocks();
});

describe("FlowCare staff login", () => {
  it("signs in and loads live overview data", async () => {
    vi.mocked(api.me).mockRejectedValue(new Error("not signed in"));
    vi.mocked(api.login).mockResolvedValue({
      id: "staff-1",
      email: "admin@example.com",
      display_name: "Demo Admin",
      role: "admin",
    });
    vi.mocked(api.overview).mockResolvedValue({
      total_registered: 0,
      waiting: 0,
      in_service: 0,
      completed: 0,
      actual_average_wait_minutes: null,
      departments: [],
      data_label: "Synthetic data",
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in to FlowCare" });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "admin@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "secure-demo-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign in/i }));

    await waitFor(() => expect(api.login).toHaveBeenCalledWith("admin@example.com", "secure-demo-password"));
    expect(await screen.findByRole("heading", { name: "Operations overview" })).toBeTruthy();
    expect(screen.getByText("Synthetic data")).toBeTruthy();
  });

  it("creates an account and opens the workspace as a receptionist", async () => {
    vi.mocked(api.me).mockRejectedValue(new Error("not signed in"));
    vi.mocked(api.signup).mockResolvedValue({
      id: "staff-2",
      email: "new@example.com",
      display_name: "New User",
      role: "receptionist",
    });
    vi.mocked(api.overview).mockResolvedValue({
      total_registered: 0,
      waiting: 0,
      in_service: 0,
      completed: 0,
      actual_average_wait_minutes: null,
      departments: [],
      data_label: "Synthetic data",
    });

    render(<App />);
    await screen.findByRole("heading", { name: "Sign in to FlowCare" });
    fireEvent.click(screen.getByRole("tab", { name: "Sign up" }));
    fireEvent.change(screen.getByLabelText("Full name"), {
      target: { value: "New User" },
    });
    fireEvent.change(screen.getByLabelText("Email address"), {
      target: { value: "new@example.com" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "private-password" },
    });
    fireEvent.click(screen.getByRole("button", { name: /sign up & enter workspace/i }));

    await waitFor(() =>
      expect(api.signup).toHaveBeenCalledWith({
        email: "new@example.com",
        password: "private-password",
        display_name: "New User",
      }),
    );
    expect(await screen.findByRole("heading", { name: "Operations overview" })).toBeTruthy();
  });
});
