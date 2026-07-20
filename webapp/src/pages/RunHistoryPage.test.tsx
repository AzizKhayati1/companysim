import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import RunHistoryPage from "./RunHistoryPage";

vi.mock("../api/client", () => ({
  api: {
    getOrg: vi.fn().mockResolvedValue({ id: 7, name: "Acme Corp", headcount: 10, seed: 1 }),
    listDepartments: vi.fn().mockResolvedValue([]),
    listTeams: vi.fn().mockResolvedValue([]),
    listRuns: vi.fn().mockResolvedValue([
      {
        id: 1,
        run_type: "simulate",
        created_at: "2026-03-05T14:30:00Z",
        summary: "single · 12 ticks · 1x · seed 1",
      },
    ]),
    getRun: vi.fn(),
    deleteRun: vi.fn(),
  },
}));

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={["/orgs/7/runs"]}>
        <Routes>
          <Route path="/orgs/:orgId/runs" element={<RunHistoryPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RunHistoryPage", () => {
  it("renders a run's timestamp in en-US format", async () => {
    renderPage();

    // Proves the §5.5 locale fix is actually visible in a rendered page,
    // not just correct in isolation — same formatDateTime() used here as
    // in format.test.ts, exercised through the real component tree. Match
    // shape (m/d/yyyy), not an exact date — the UTC->local conversion in
    // formatDateTime makes the exact day timezone-dependent.
    const cell = await screen.findByText(/^\d{1,2}\/\d{1,2}\/2026/);
    expect(cell).toBeInTheDocument();
  });

  it("renders the run summary and type", async () => {
    renderPage();
    expect(await screen.findByText("single · 12 ticks · 1x · seed 1")).toBeInTheDocument();
    expect(await screen.findByText("simulate")).toBeInTheDocument();
  });
});
