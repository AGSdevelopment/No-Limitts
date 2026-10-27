// Staff groups used to control who can see each Jotform. Admins always see every form.
export const STAFF_GROUPS = [
  { key: "support_office", label: "Support Office" },
  { key: "therapist_employee", label: "Therapist Employees" },
  { key: "therapist_contractor", label: "Therapist Contractors" },
  { key: "support_worker_employee", label: "Support Worker Employees" },
  { key: "support_worker_contractor", label: "Support Worker Contractors" },
  { key: "new_starter_employee", label: "New Starter Employees" },
  { key: "new_starter_contractor", label: "New Starter Contractors" },
] as const;

export type StaffGroup = (typeof STAFF_GROUPS)[number]["key"];

export function groupLabel(key?: string | null) {
  return STAFF_GROUPS.find((g) => g.key === key)?.label ?? "";
}

export function audienceLabel(audiences?: string[]) {
  if (!audiences || audiences.length === 0) return "Everyone";
  return audiences.map(groupLabel).filter(Boolean).join(", ");
}

export const FORM_CATEGORIES = [
  "Day-to-Day",
  "New Starter",
  "HR",
  "Compliance",
  "Referral Triage",
  "Therapy Triage",
  "Support Office",
] as const;
