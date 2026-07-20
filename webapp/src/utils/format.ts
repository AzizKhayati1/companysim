// Locale pinned explicitly everywhere — toLocaleString() without one
// renders differently depending on the browser's default locale (e.g.
// "$185 236,415" instead of "$185,236"), a real bug caught and fixed
// during this project's build (see docs/project_overview.md §5.5).

export function formatCurrency(amount: number): string {
  return amount.toLocaleString("en-US", { maximumFractionDigits: 0 });
}

export function formatDateTime(iso: string): string {
  return new Date(iso).toLocaleString("en-US");
}
