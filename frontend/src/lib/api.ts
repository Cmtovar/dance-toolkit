const BASE = ''

export interface Routine {
  id: number
  name: string
  created: string
  move_count?: number
  solid_count?: number
  timing_floor?: number | null
  alternates?: Alternate[]
  moves?: Move[]
}

export interface Alternate {
  id: number
  routine_id: number
  youtube_url: string
  label: string
  is_mirrored: number
  notes: string
  sort_order: number
}

export interface Move {
  id: number
  routine_id: number
  alternate_id: number | null
  name: string
  start_time: number
  end_time: number
  max_clean_speed: number
  status: 'learning' | 'practicing' | 'solid' | 'mastered'
  last_drilled: string | null
  drill_count: number
  sort_order: number
}

async function request(path: string, options?: RequestInit) {
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options?.headers },
  })
  return res.json()
}

export const api = {
  listRoutines: (): Promise<Routine[]> => request('/api/routines'),

  getRoutine: (id: number): Promise<Routine> => request(`/api/routines/${id}`),

  createRoutine: (data: { name: string; youtube_url?: string; label?: string }): Promise<Routine> =>
    request('/api/routines', { method: 'POST', body: JSON.stringify(data) }),

  updateRoutine: (id: number, data: { name: string }): Promise<Routine> =>
    request(`/api/routines/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteRoutine: (id: number): Promise<void> =>
    request(`/api/routines/${id}`, { method: 'DELETE' }),

  createAlternate: (routineId: number, data: { youtube_url: string; label?: string; is_mirrored?: number; notes?: string }): Promise<Alternate> =>
    request(`/api/routines/${routineId}/alternates`, { method: 'POST', body: JSON.stringify(data) }),

  updateAlternate: (routineId: number, id: number, data: Partial<Alternate>): Promise<Alternate> =>
    request(`/api/routines/${routineId}/alternates/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteAlternate: (routineId: number, id: number): Promise<void> =>
    request(`/api/routines/${routineId}/alternates/${id}`, { method: 'DELETE' }),

  createMove: (routineId: number, data: { name: string; start_time: number; end_time: number; alternate_id?: number }): Promise<Move> =>
    request(`/api/routines/${routineId}/moves`, { method: 'POST', body: JSON.stringify(data) }),

  updateMove: (routineId: number, id: number, data: Partial<Move>): Promise<Move> =>
    request(`/api/routines/${routineId}/moves/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  deleteMove: (routineId: number, id: number): Promise<void> =>
    request(`/api/routines/${routineId}/moves/${id}`, { method: 'DELETE' }),

  drillMove: (routineId: number, id: number): Promise<Move> =>
    request(`/api/routines/${routineId}/moves/${id}/drill`, { method: 'POST' }),
}
