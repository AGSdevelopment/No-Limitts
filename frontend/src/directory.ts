import type { IconName } from "@/src/components/ui";

export type DirSpace = "therapist" | "participant";

export const SPACE_LABEL: Record<DirSpace, string> = { therapist: "Therapist", participant: "Participants" };

export const CATEGORIES: Record<DirSpace, string[]> = {
  therapist: ["Suppliers", "Templates", "Trusted Referral Partner Organisations"],
  participant: ["Suppliers", "Activities", "Resources"],
};

export const CAT_ICON: Record<string, IconName> = {
  Suppliers: "storefront-outline",
  Templates: "copy-outline",
  "Trusted Referral Partner Organisations": "people-circle-outline",
  Activities: "bicycle-outline",
  Resources: "library-outline",
};
