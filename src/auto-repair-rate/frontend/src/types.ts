export type EvidenceStatus = 'entered' | 'factory_reported' | 'assumed' | 'unknown' | 'terms_unverified';
export type HoursBasis = 'total_person_hours' | 'billable_person_hours';
export type RateStatus = 'draft' | 'blocked' | 'approved';
export interface BasisRow { label: string; value: number | string | null; unit: string; }
export interface HoursRange { low: number; typical: number; high: number; }

export interface Evidence {
  label: string;
  value: number | string | null;
  unit: string;
  status: EvidenceStatus;
  source: string | null;
  evidence_ref: string | null;
  recorded_at: string;
  notes: string | null;
}

export interface CostItem {
  cost_id: string;
  label: string;
  amount_yen: number | null;
  period: string;
  source: string | null;
  evidence_status: EvidenceStatus;
  billing_class: 'labor_pool' | 'separately_billed_item' | 'other';
  included_in_labor_pool: boolean;
  excluded_reason: string | null;
}

export interface RateProposal {
  proposal_id?: string;
  module_id: string;
  period_start: string;
  period_end: string | null;
  effective_from: string;
  allocable_cost_yen: number | null;
  period_total_person_hours: number | null;
  u_period: number | null;
  hours_basis: HoursBasis | null;
  job_person_hours: HoursRange | null;
  job_billable_ratio: number | null;
  costs: CostItem[];
  evidence: Evidence[];
  source: string;
  notes: string | null;
}

export interface ApprovalRequest {
  approved_yen_per_person_hour: number;
  effective_from: string;
  approved_by: string;
  approval_reason: string;
}

export interface ModuleDescriptor {
  module_id: string;
  title: string;
  description: string;
}

export interface LaborRate {
  yen_per_person_hour: number;
  effective_from: string;
  basis: BasisRow[];
}

export interface RateVersion {
  proposal_id: string;
  module_id: string;
  rate_scope: string;
  rate_type: 'customer' | 'internal';
  status: RateStatus;
  calculation: {
    status: RateStatus;
    candidate_yen_per_person_hour: number | null;
    denominator_person_hours: number | null;
    hours_basis: HoursBasis | null;
    u_period: number | null;
    job_billable_person_hours: HoursRange | null;
    job_unknowns: string[];
    job_billable_ratio: number | null;
    unknowns: string[];
    excluded_items: CostItem[];
    basis: LaborRate['basis'];
  };
  labor_rate: LaborRate | null;
  source: string;
  evidence: Evidence[];
  approved_by: string | null;
  approval_reason: string | null;
  created_at: string;
}

export interface RateHistoryRecord {
  rate_id: string;
  proposal_id: string;
  rate_scope: string;
  rate_type: 'customer' | 'internal';
  labor_rate: LaborRate;
  effective_to: string | null;
  approval_id: string;
  approved_by: string;
  approval_reason: string;
  created_at: string;
}
