import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, Outlet, useLocation, useParams } from "react-router-dom";
import { api } from "../api/client";
import { useTheme } from "../theme/ThemeContext";
import AskVantageWidget from "./AskVantageWidget";

interface NavItem {
  key: string;
  label: string;
  to: (orgId: number) => string;
  icon: ReactNode;
  match: (pathname: string) => boolean;
}

const MAIN_NAV: NavItem[] = [
  {
    key: "dashboard",
    label: "Dashboard",
    to: (orgId) => `/orgs/${orgId}`,
    match: (p) => /^\/orgs\/\d+$/.test(p),
    icon: (
      <svg width="16" height="16" viewBox="0 0 20 20">
        <rect x="2" y="2" width="7" height="7" rx="1.6" fill="currentColor" />
        <rect x="11" y="2" width="7" height="7" rx="1.6" fill="currentColor" opacity="0.4" />
        <rect x="2" y="11" width="7" height="7" rx="1.6" fill="currentColor" opacity="0.4" />
        <rect x="11" y="11" width="7" height="7" rx="1.6" fill="currentColor" />
      </svg>
    ),
  },
  {
    key: "editor",
    label: "Org Structure",
    to: (orgId) => `/orgs/${orgId}/editor`,
    match: (p) => /^\/orgs\/\d+\/editor$/.test(p),
    icon: (
      <svg width="16" height="16" viewBox="0 0 20 20">
        <circle cx="10" cy="4" r="2.4" fill="currentColor" />
        <circle cx="4" cy="16" r="2.4" fill="currentColor" opacity="0.6" />
        <circle cx="16" cy="16" r="2.4" fill="currentColor" opacity="0.6" />
        <line x1="10" y1="6.4" x2="4" y2="13.6" stroke="currentColor" strokeWidth="1.4" />
        <line x1="10" y1="6.4" x2="16" y2="13.6" stroke="currentColor" strokeWidth="1.4" />
      </svg>
    ),
  },
  {
    key: "simulate",
    label: "Scenario Simulator",
    to: (orgId) => `/orgs/${orgId}/simulate`,
    match: (p) => /^\/orgs\/\d+\/simulate$/.test(p),
    icon: (
      <svg width="16" height="16" viewBox="0 0 20 20">
        <rect x="2" y="11" width="3.4" height="7" rx="1" fill="currentColor" opacity="0.5" />
        <rect x="8.3" y="6" width="3.4" height="12" rx="1" fill="currentColor" />
        <rect x="14.6" y="2" width="3.4" height="16" rx="1" fill="currentColor" opacity="0.75" />
      </svg>
    ),
  },
  {
    key: "atrisk",
    label: "Retention Risk",
    to: (orgId) => `/orgs/${orgId}/at-risk`,
    match: (p) => /^\/orgs\/\d+\/at-risk$/.test(p) || /^\/orgs\/\d+\/employees\/\d+\/risk-history$/.test(p),
    icon: (
      <svg width="16" height="16" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <line x1="10" y1="6" x2="10" y2="11" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
        <circle cx="10" cy="14" r="1" fill="currentColor" />
      </svg>
    ),
  },
];

const SECONDARY_NAV: NavItem[] = [
  {
    key: "runs",
    label: "Run History",
    to: (orgId) => `/orgs/${orgId}/runs`,
    match: (p) => /^\/orgs\/\d+\/runs$/.test(p),
    icon: (
      <svg width="16" height="16" viewBox="0 0 20 20">
        <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <path d="M10 5.5 V10 L13.2 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      </svg>
    ),
  },
  {
    key: "model",
    label: "Turnover Model",
    to: () => "/model",
    match: (p) => p === "/model",
    icon: (
      <svg width="16" height="16" viewBox="0 0 20 20">
        <path d="M2 16 L7 9 L11 12 L18 3" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="18" cy="3" r="1.6" fill="currentColor" />
      </svg>
    ),
  },
];

export default function AppShell() {
  const { orgId: orgIdStr } = useParams();
  const orgId = orgIdStr ? Number(orgIdStr) : undefined;
  const location = useLocation();
  const { theme, toggleTheme } = useTheme();

  const orgQuery = useQuery({
    queryKey: ["org", orgId],
    queryFn: () => api.getOrg(orgId!),
    enabled: orgId !== undefined,
  });
  const org = orgQuery.data;

  const initials = org
    ? org.name.split(" ").map((p) => p[0]).join("").slice(0, 2).toUpperCase()
    : "--";

  return (
    <div className="app-shell-layout">
      <aside className="sidebar">
        <div className="sidebar-brand">
          <div className="sidebar-brand-mark" />
          <div>
            <div className="sidebar-brand-name">Vantage</div>
            <div className="sidebar-brand-sub">HR Intelligence</div>
          </div>
        </div>

        <nav className="sidebar-nav">
          {MAIN_NAV.map((item) => {
            const active = item.match(location.pathname);
            const disabled = orgId === undefined;
            return (
              <Link
                key={item.key}
                to={disabled ? "#" : item.to(orgId)}
                className={`sidebar-nav-item${active ? " active" : ""}${disabled ? " disabled" : ""}`}
                aria-disabled={disabled}
              >
                <span className="sidebar-nav-icon">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="sidebar-divider" />

        <nav className="sidebar-nav">
          {SECONDARY_NAV.map((item) => {
            const active = item.match(location.pathname);
            const disabled = item.key === "runs" && orgId === undefined;
            return (
              <Link
                key={item.key}
                to={disabled ? "#" : item.to(orgId as number)}
                className={`sidebar-nav-item${active ? " active" : ""}${disabled ? " disabled" : ""}`}
                aria-disabled={disabled}
              >
                <span className="sidebar-nav-icon">{item.icon}</span>
                {item.label}
              </Link>
            );
          })}
        </nav>

        <div className="spacer" />

        <div className="sidebar-footer">
          <div className="sidebar-appearance-row">
            <div className="sidebar-appearance-label">
              <svg width="15" height="15" viewBox="0 0 20 20">
                <circle cx="10" cy="10" r="8" fill="none" stroke="currentColor" strokeWidth="1.4" />
                <path d="M10 2 A8 8 0 0 0 10 18 Z" fill="currentColor" />
              </svg>
              Appearance
            </div>
            <button
              type="button"
              className={`theme-toggle${theme === "dark" ? " on" : ""}`}
              onClick={toggleTheme}
              aria-label="Toggle dark mode"
            >
              <span className="theme-toggle-knob" />
            </button>
          </div>

          <Link to="/" className="sidebar-org-card">
            <div className="sidebar-org-initials">{initials}</div>
            <div className="sidebar-org-info">
              <div className="sidebar-org-name">{org?.name ?? "Switch org"}</div>
              <div className="sidebar-org-headcount">
                {org ? `${org.headcount} people` : "All orgs"}
              </div>
            </div>
          </Link>
        </div>
      </aside>

      <main className="app-main">
        <div className="app-main-inner">
          <Outlet />
        </div>
      </main>

      {orgId !== undefined && <AskVantageWidget key={orgId} orgId={orgId} />}
    </div>
  );
}
