import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";

export default function OrgListPage() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: orgs, isLoading, error } = useQuery({
    queryKey: ["orgs"],
    queryFn: api.listOrgs,
  });

  const [name, setName] = useState("Acme Corp");
  const [headcount, setHeadcount] = useState(200);
  const [seed, setSeed] = useState(42);

  const createMutation = useMutation({
    mutationFn: () => api.createOrg(name, headcount, seed),
    onSuccess: (org) => {
      queryClient.invalidateQueries({ queryKey: ["orgs"] });
      navigate(`/orgs/${org.id}`);
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (orgId: number) => api.deleteOrg(orgId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["orgs"] }),
  });

  return (
    <div className="page">
      <h1>Digital Workforce Twin</h1>
      <p className="muted">
        Create a synthetic company, edit its employees/departments/teams, then run
        the simulation against your edits.
      </p>

      <div className="card">
        <h2>Create a new org</h2>
        <div className="row">
          <label>
            Name{" "}
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label>
            Headcount{" "}
            <input
              type="number"
              min={2}
              max={5000}
              value={headcount}
              onChange={(e) => setHeadcount(Number(e.target.value))}
            />
          </label>
          <label>
            Seed{" "}
            <input
              type="number"
              value={seed}
              onChange={(e) => setSeed(Number(e.target.value))}
            />
          </label>
          <button
            className="btn btn-primary"
            disabled={createMutation.isPending}
            onClick={() => createMutation.mutate()}
          >
            {createMutation.isPending ? "Generating..." : "Create"}
          </button>
        </div>
        {createMutation.isError && (
          <p className="error">{(createMutation.error as Error).message}</p>
        )}
      </div>

      <h2>Existing orgs</h2>
      {isLoading && <p className="muted">Loading...</p>}
      {error && <p className="error">{(error as Error).message}</p>}
      {orgs && orgs.length === 0 && <p className="muted">No orgs yet — create one above.</p>}
      {orgs && orgs.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Headcount</th>
                <th>Departments</th>
                <th>Teams</th>
                <th>Seed</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {orgs.map((org) => (
                <tr key={org.id}>
                  <td>{org.id}</td>
                  <td>{org.name}</td>
                  <td>{org.headcount}</td>
                  <td>{org.department_count}</td>
                  <td>{org.team_count}</td>
                  <td>{org.seed}</td>
                  <td className="row">
                    <button className="btn" onClick={() => navigate(`/orgs/${org.id}`)}>
                      Edit
                    </button>
                    <button
                      className="btn"
                      onClick={() => navigate(`/orgs/${org.id}/simulate`)}
                    >
                      Simulate
                    </button>
                    <button
                      className="btn btn-danger"
                      onClick={() => {
                        if (confirm(`Delete org "${org.name}"?`)) {
                          deleteMutation.mutate(org.id);
                        }
                      }}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
