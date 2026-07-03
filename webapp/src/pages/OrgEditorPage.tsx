import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import { LEVELS, WORK_MODES, type EmployeeIn } from "../types";

export default function OrgEditorPage() {
  const { orgId: orgIdStr } = useParams();
  const orgId = Number(orgIdStr);
  const queryClient = useQueryClient();

  const orgQuery = useQuery({ queryKey: ["org", orgId], queryFn: () => api.getOrg(orgId) });
  const deptsQuery = useQuery({
    queryKey: ["departments", orgId],
    queryFn: () => api.listDepartments(orgId),
  });
  const teamsQuery = useQuery({
    queryKey: ["teams", orgId],
    queryFn: () => api.listTeams(orgId),
  });
  const empsQuery = useQuery({
    queryKey: ["employees", orgId],
    queryFn: () => api.listEmployees(orgId),
  });

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ["org", orgId] });
    queryClient.invalidateQueries({ queryKey: ["departments", orgId] });
    queryClient.invalidateQueries({ queryKey: ["teams", orgId] });
    queryClient.invalidateQueries({ queryKey: ["employees", orgId] });
  };

  const updateDept = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string; salary_multiplier?: number } }) =>
      api.updateDepartment(orgId, id, body),
    onSuccess: invalidateAll,
  });
  const deleteDept = useMutation({
    mutationFn: (id: number) => api.deleteDepartment(orgId, id),
    onSuccess: invalidateAll,
    onError: (e) => alert((e as Error).message),
  });
  const createDept = useMutation({
    mutationFn: (name: string) => api.createDepartment(orgId, { name, salary_multiplier: 1.0 }),
    onSuccess: invalidateAll,
  });

  const updateTeam = useMutation({
    mutationFn: ({ id, body }: { id: number; body: { name?: string; department_id?: number } }) =>
      api.updateTeam(orgId, id, body),
    onSuccess: invalidateAll,
  });
  const deleteTeam = useMutation({
    mutationFn: (id: number) => api.deleteTeam(orgId, id),
    onSuccess: invalidateAll,
    onError: (e) => alert((e as Error).message),
  });
  const createTeam = useMutation({
    mutationFn: ({ name, department_id }: { name: string; department_id: number }) =>
      api.createTeam(orgId, { name, department_id }),
    onSuccess: invalidateAll,
  });

  const updateEmp = useMutation({
    mutationFn: ({ id, body }: { id: number; body: EmployeeIn }) =>
      api.updateEmployee(orgId, id, body),
    onSuccess: invalidateAll,
  });
  const deleteEmp = useMutation({
    mutationFn: (id: number) => api.deleteEmployee(orgId, id),
    onSuccess: invalidateAll,
  });
  const createEmp = useMutation({
    mutationFn: (body: EmployeeIn) => api.createEmployee(orgId, body),
    onSuccess: invalidateAll,
  });

  const [newDeptName, setNewDeptName] = useState("");
  const [newTeamName, setNewTeamName] = useState("");
  const [newTeamDept, setNewTeamDept] = useState<number | "">("");
  const [newEmpName, setNewEmpName] = useState("");
  const [newEmpDept, setNewEmpDept] = useState<number | "">("");
  const [newEmpTeam, setNewEmpTeam] = useState<number | "">("");

  if (orgQuery.isLoading) return <div className="page">Loading...</div>;
  if (orgQuery.error) return <div className="page error">{(orgQuery.error as Error).message}</div>;

  const depts = deptsQuery.data ?? [];
  const teams = teamsQuery.data ?? [];
  const emps = empsQuery.data ?? [];
  const teamsInDept = (deptId: number | "") => teams.filter((t) => t.department_id === deptId);

  return (
    <div className="page">
      <div className="row" style={{ marginBottom: 16 }}>
        <Link to="/">&larr; All orgs</Link>
        <div className="spacer" />
        <Link className="btn btn-primary" to={`/orgs/${orgId}/simulate`}>
          Run simulation &rarr;
        </Link>
      </div>
      <h1>{orgQuery.data?.name}</h1>
      <p className="muted">
        {orgQuery.data?.headcount} employees · {orgQuery.data?.department_count} departments ·{" "}
        {orgQuery.data?.team_count} teams
      </p>

      <div className="grid-2">
        <div className="card">
          <h2>Departments</h2>
          <div className="table-wrap" style={{ maxHeight: 260 }}>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Salary &times;</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {depts.map((d) => (
                  <tr key={d.id}>
                    <td>
                      <input
                        defaultValue={d.name}
                        onBlur={(e) =>
                          e.target.value !== d.name &&
                          updateDept.mutate({ id: d.id, body: { name: e.target.value } })
                        }
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        step="0.01"
                        defaultValue={d.salary_multiplier}
                        onBlur={(e) =>
                          Number(e.target.value) !== d.salary_multiplier &&
                          updateDept.mutate({
                            id: d.id,
                            body: { salary_multiplier: Number(e.target.value) },
                          })
                        }
                      />
                    </td>
                    <td>
                      <button className="btn btn-danger" onClick={() => deleteDept.mutate(d.id)}>
                        &times;
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <input
              placeholder="New department name"
              value={newDeptName}
              onChange={(e) => setNewDeptName(e.target.value)}
            />
            <button
              className="btn"
              disabled={!newDeptName}
              onClick={() => {
                createDept.mutate(newDeptName);
                setNewDeptName("");
              }}
            >
              + Add
            </button>
          </div>
        </div>

        <div className="card">
          <h2>Teams</h2>
          <div className="table-wrap" style={{ maxHeight: 260 }}>
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Department</th>
                  <th>Members</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {teams.map((t) => (
                  <tr key={t.id}>
                    <td>
                      <input
                        defaultValue={t.name}
                        onBlur={(e) =>
                          e.target.value !== t.name &&
                          updateTeam.mutate({ id: t.id, body: { name: e.target.value } })
                        }
                      />
                    </td>
                    <td>
                      <select
                        defaultValue={t.department_id}
                        onChange={(e) =>
                          updateTeam.mutate({
                            id: t.id,
                            body: { department_id: Number(e.target.value) },
                          })
                        }
                      >
                        {depts.map((d) => (
                          <option key={d.id} value={d.id}>
                            {d.name}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>{t.member_count}</td>
                    <td>
                      <button className="btn btn-danger" onClick={() => deleteTeam.mutate(t.id)}>
                        &times;
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            <input
              placeholder="New team name"
              value={newTeamName}
              onChange={(e) => setNewTeamName(e.target.value)}
            />
            <select
              value={newTeamDept}
              onChange={(e) => setNewTeamDept(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Department...</option>
              {depts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <button
              className="btn"
              disabled={!newTeamName || newTeamDept === ""}
              onClick={() => {
                createTeam.mutate({ name: newTeamName, department_id: newTeamDept as number });
                setNewTeamName("");
                setNewTeamDept("");
              }}
            >
              + Add
            </button>
          </div>
        </div>
      </div>

      <div className="card">
        <h2>Employees ({emps.length})</h2>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Department</th>
                <th>Team</th>
                <th>Level</th>
                <th>Role</th>
                <th>Tenure (mo)</th>
                <th>Salary</th>
                <th>Work mode</th>
                <th title="Perceived workload, 0-1">Workload</th>
                <th title="Manager support, 0-1">Mgr support</th>
                <th title="Psychological safety, 0-1">Psych safety</th>
                <th title="Financial security, 0-1">Fin. security</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {emps.map((e) => (
                <tr key={e.id}>
                  <td>
                    <input
                      defaultValue={e.full_name}
                      onBlur={(ev) =>
                        ev.target.value !== e.full_name &&
                        updateEmp.mutate({ id: e.id, body: { full_name: ev.target.value } })
                      }
                    />
                  </td>
                  <td>
                    <select
                      defaultValue={e.department_id}
                      onChange={(ev) =>
                        updateEmp.mutate({
                          id: e.id,
                          body: { department_id: Number(ev.target.value) },
                        })
                      }
                    >
                      {depts.map((d) => (
                        <option key={d.id} value={d.id}>
                          {d.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      defaultValue={e.team_id}
                      onChange={(ev) =>
                        updateEmp.mutate({ id: e.id, body: { team_id: Number(ev.target.value) } })
                      }
                    >
                      {teamsInDept(e.department_id).map((t) => (
                        <option key={t.id} value={t.id}>
                          {t.name}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <select
                      defaultValue={e.level}
                      onChange={(ev) =>
                        updateEmp.mutate({ id: e.id, body: { level: ev.target.value } })
                      }
                    >
                      {LEVELS.map((l) => (
                        <option key={l} value={l}>
                          {l}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    <input
                      defaultValue={e.role}
                      onBlur={(ev) =>
                        ev.target.value !== e.role &&
                        updateEmp.mutate({ id: e.id, body: { role: ev.target.value } })
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      defaultValue={e.tenure_months}
                      onBlur={(ev) =>
                        Number(ev.target.value) !== e.tenure_months &&
                        updateEmp.mutate({
                          id: e.id,
                          body: { tenure_months: Number(ev.target.value) },
                        })
                      }
                    />
                  </td>
                  <td>
                    <input
                      type="number"
                      defaultValue={e.base_salary}
                      onBlur={(ev) =>
                        Number(ev.target.value) !== e.base_salary &&
                        updateEmp.mutate({
                          id: e.id,
                          body: { base_salary: Number(ev.target.value) },
                        })
                      }
                    />
                  </td>
                  <td>
                    <select
                      defaultValue={e.work_mode}
                      onChange={(ev) =>
                        updateEmp.mutate({ id: e.id, body: { work_mode: ev.target.value } })
                      }
                    >
                      {WORK_MODES.map((m) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </select>
                  </td>
                  {(
                    [
                      "workload_perceived",
                      "manager_support_score",
                      "psychological_safety_perceived",
                      "financial_security_score",
                    ] as const
                  ).map((field) => (
                    <td key={field}>
                      <input
                        type="number"
                        min={0}
                        max={1}
                        step="0.05"
                        defaultValue={e[field]}
                        onBlur={(ev) =>
                          Number(ev.target.value) !== e[field] &&
                          updateEmp.mutate({
                            id: e.id,
                            body: { [field]: Number(ev.target.value) },
                          })
                        }
                      />
                    </td>
                  ))}
                  <td>
                    <button className="btn btn-danger" onClick={() => deleteEmp.mutate(e.id)}>
                      &times;
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <div className="row" style={{ marginTop: 10 }}>
          <input
            placeholder="New employee name"
            value={newEmpName}
            onChange={(e) => setNewEmpName(e.target.value)}
          />
          <select
            value={newEmpDept}
            onChange={(e) => {
              setNewEmpDept(e.target.value ? Number(e.target.value) : "");
              setNewEmpTeam("");
            }}
          >
            <option value="">Department...</option>
            {depts.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
          <select
            value={newEmpTeam}
            onChange={(e) => setNewEmpTeam(e.target.value ? Number(e.target.value) : "")}
            disabled={newEmpDept === ""}
          >
            <option value="">Team...</option>
            {teamsInDept(newEmpDept).map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
          <button
            className="btn"
            disabled={!newEmpName || newEmpDept === "" || newEmpTeam === ""}
            onClick={() => {
              createEmp.mutate({
                full_name: newEmpName,
                department_id: newEmpDept as number,
                team_id: newEmpTeam as number,
              });
              setNewEmpName("");
              setNewEmpDept("");
              setNewEmpTeam("");
            }}
          >
            + Add employee
          </button>
        </div>
      </div>
    </div>
  );
}
