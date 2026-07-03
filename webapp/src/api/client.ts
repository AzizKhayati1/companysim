import type {
  DepartmentIn,
  DepartmentOut,
  DiagnoseResponse,
  EmployeeIn,
  EmployeeOut,
  OrgSummary,
  SimulateRequest,
  SimulateResponse,
  TeamIn,
  TeamOut,
} from "../types";

const API_BASE = "http://localhost:8611";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // ignore — use statusText
    }
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listOrgs: () => request<OrgSummary[]>("/orgs"),
  createOrg: (name: string, headcount: number, seed: number) =>
    request<OrgSummary>("/orgs", {
      method: "POST",
      body: JSON.stringify({ name, headcount, seed }),
    }),
  getOrg: (orgId: number) => request<OrgSummary>(`/orgs/${orgId}`),
  deleteOrg: (orgId: number) => request<void>(`/orgs/${orgId}`, { method: "DELETE" }),

  listDepartments: (orgId: number) => request<DepartmentOut[]>(`/orgs/${orgId}/departments`),
  createDepartment: (orgId: number, body: DepartmentIn) =>
    request<DepartmentOut>(`/orgs/${orgId}/departments`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateDepartment: (orgId: number, deptId: number, body: DepartmentIn) =>
    request<DepartmentOut>(`/orgs/${orgId}/departments/${deptId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteDepartment: (orgId: number, deptId: number) =>
    request<void>(`/orgs/${orgId}/departments/${deptId}`, { method: "DELETE" }),

  listTeams: (orgId: number) => request<TeamOut[]>(`/orgs/${orgId}/teams`),
  createTeam: (orgId: number, body: TeamIn) =>
    request<TeamOut>(`/orgs/${orgId}/teams`, { method: "POST", body: JSON.stringify(body) }),
  updateTeam: (orgId: number, teamId: number, body: TeamIn) =>
    request<TeamOut>(`/orgs/${orgId}/teams/${teamId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteTeam: (orgId: number, teamId: number) =>
    request<void>(`/orgs/${orgId}/teams/${teamId}`, { method: "DELETE" }),

  listEmployees: (orgId: number) => request<EmployeeOut[]>(`/orgs/${orgId}/employees`),
  createEmployee: (orgId: number, body: EmployeeIn) =>
    request<EmployeeOut>(`/orgs/${orgId}/employees`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateEmployee: (orgId: number, empId: number, body: EmployeeIn) =>
    request<EmployeeOut>(`/orgs/${orgId}/employees/${empId}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  deleteEmployee: (orgId: number, empId: number) =>
    request<void>(`/orgs/${orgId}/employees/${empId}`, { method: "DELETE" }),

  simulate: (orgId: number, body: SimulateRequest) =>
    request<SimulateResponse>(`/orgs/${orgId}/simulate`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  diagnose: (orgId: number, body: SimulateRequest) =>
    request<DiagnoseResponse>(`/orgs/${orgId}/diagnose`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
