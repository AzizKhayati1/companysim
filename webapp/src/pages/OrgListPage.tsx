import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
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
      <div className="row" style={{ marginBottom: 16 }}>
        <div className="spacer" />
        <Link className="btn" to="/model">Turnover model</Link>
      </div>
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
        <div className="data-list">
          <div className="data-list-scroll">
            <div
              className="data-list-header"
              style={{ gridTemplateColumns: "1fr 90px 110px 80px 70px 320px" }}
            >
              <div>Name</div>
              <div>Headcount</div>
              <div>Departments</div>
              <div>Teams</div>
              <div>Seed</div>
              <div></div>
            </div>
            {orgs.map((org) => (
              <div
                className="data-list-row"
                key={org.id}
                style={{ gridTemplateColumns: "1fr 90px 110px 80px 70px 320px" }}
              >
                <div className="data-list-cell">
                  <strong>{org.name}</strong>
                </div>
                <div className="data-list-cell">{org.headcount}</div>
                <div className="data-list-cell">{org.department_count}</div>
                <div className="data-list-cell">{org.team_count}</div>
                <div className="data-list-cell">{org.seed}</div>
                <div className="data-list-cell actions">
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
                    className="btn"
                    onClick={() => navigate(`/orgs/${org.id}/at-risk`)}
                  >
                    At-Risk
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
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
