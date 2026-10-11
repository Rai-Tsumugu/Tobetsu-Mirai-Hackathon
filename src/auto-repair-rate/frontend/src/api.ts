import type { ApprovalRequest, ModuleDescriptor, RateHistoryRecord, RateProposal, RateVersion } from './types';

const API_BASE = import.meta.env.VITE_API_BASE ?? '';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || `API error ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  create_proposal: (proposal: RateProposal) => request<RateVersion>('/api/auto-repair-rate/proposals', {
    method: 'POST', body: JSON.stringify({ proposal }),
  }),
  get_proposal: (id: string) => request<RateVersion>(`/api/auto-repair-rate/proposals/${encodeURIComponent(id)}`),
  approve_proposal: (id: string, approval: ApprovalRequest) => request<RateVersion>(`/api/auto-repair-rate/proposals/${encodeURIComponent(id)}/approval`, {
    method: 'POST', body: JSON.stringify(approval),
  }),
  list_rates: () => request<RateHistoryRecord[]>('/api/auto-repair-rate/labor-rates'),
  list_proposals: () => request<RateVersion[]>('/api/auto-repair-rate/proposals?limit=30'),
  list_modules: () => request<ModuleDescriptor[]>('/api/auto-repair-rate/modules'),
};
