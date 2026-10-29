// Staff groups used to control who can see each Jotform. Admins always see every form.
export const STAFF_GROUPS = [
  { key: "support_office", label: "Support Office" },
  { key: "support_coordinator", label: "Service & Support Coordinators" },
  { key: "support_worker", label: "Support Workers" },
] as const;

export type StaffGroup = (typeof STAFF_GROUPS)[number]["key"];

export function groupLabel(key?: string | null) {
  return STAFF_GROUPS.find((g) => g.key === key)?.label ?? "";
}

export const USER_TYPES = [
  { key: "executive", label: "Executive", hint: "Admin tools, and can manage other Executives · Microsoft sign-in" },
  { key: "admin", label: "Admin", hint: "Admin tools · Microsoft sign-in" },
  { key: "support_office", label: "Support Office", hint: "Office staff · Microsoft sign-in" },
  { key: "support_coordinator", label: "Service & Support Coordinator", hint: "Participant management & onboarding forms · Microsoft sign-in" },
  { key: "support_worker", label: "Support Worker", hint: "Signs in with an email and password you issue" },
] as const;

export function typeLabel(key?: string | null) {
  return USER_TYPES.find((t) => t.key === key)?.label ?? "";
}

export function audienceLabel(audiences?: string[]) {
  if (!audiences || audiences.length === 0) return "Everyone";
  return audiences.map(groupLabel).filter(Boolean).join(", ");
}

export const FORM_CATEGORIES = [
  "Operations",
  "Day-to-Day",
  "HR",
  "Participant Management & Onboarding",
  "New Starter",
  "HR",
  "Compliance",
  "Referral Triage",
  "Therapy Triage",
  "Support Office",
] as const;
