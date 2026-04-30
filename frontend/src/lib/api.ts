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
  attempts?: Attempt[]
}

export interface Attempt {
  id: number
  move_id: number
  youtube_url: string | null
  mime_type: string
  upload_status: 'pending' | 'on_youtube'
  recorded: string
  notes: string
}

export interface AttemptWithContext extends Attempt {
  move_name: string
  start_time: number
  routine_id: number
  routine_name: string
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

  downloadVideo: (routineId: number): Promise<{ status: string }> =>
    request(`/api/routines/${routineId}/download-video`, { method: 'POST' }),

  videoStatus: (routineId: number): Promise<{ available: boolean; size: number; status: string; error: string | null }> =>
    request(`/api/routines/${routineId}/video/status`),

  videoUrl: (routineId: number): string =>
    `${BASE}/api/routines/${routineId}/video`,

  fetchVideoBlob: (routineId: number): Promise<Blob> =>
    fetch(`${BASE}/api/routines/${routineId}/video`).then(r => r.blob()),

  createAttempt: (routineId: number, moveId: number, data: { mime_type?: string; notes?: string }): Promise<Attempt> =>
    request(`/api/routines/${routineId}/moves/${moveId}/attempts`, { method: 'POST', body: JSON.stringify(data) }),

  updateAttempt: (id: number, data: Partial<Attempt>): Promise<Attempt> =>
    request(`/api/attempts/${id}`, { method: 'PUT', body: JSON.stringify(data) }),

  listAttempts: (routineId: number, moveId: number): Promise<Attempt[]> =>
    request(`/api/routines/${routineId}/moves/${moveId}/attempts`),

  deleteAttempt: (routineId: number, moveId: number, attemptId: number): Promise<void> =>
    request(`/api/routines/${routineId}/moves/${moveId}/attempts/${attemptId}`, { method: 'DELETE' }),

  allAttempts: (): Promise<AttemptWithContext[]> => request('/api/attempts'),

  getYouTubeToken: (): Promise<{ access_token: string }> =>
    request('/api/youtube/token'),

  /** Upload a blob directly to YouTube using an access token from Pi. Returns video ID. */
  uploadToYouTube: async (blob: Blob, title: string): Promise<string> => {
    const { access_token } = await api.getYouTubeToken()

    // Initiate resumable upload
    const initRes = await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${access_token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        snippet: { title, description: 'Dance practice attempt', categoryId: '22' },
        status: { privacyStatus: 'unlisted' },
      }),
    })

    if (!initRes.ok) {
      const err = await initRes.text()
      throw new Error(`YouTube init failed: ${err.slice(0, 200)}`)
    }

    const uploadUrl = initRes.headers.get('Location')
    if (!uploadUrl) throw new Error('No upload URL returned')

    // Upload the video data
    const uploadRes = await fetch(uploadUrl, {
      method: 'PUT',
      headers: { 'Content-Type': blob.type || 'video/webm' },
      body: blob,
    })

    if (!uploadRes.ok) {
      const err = await uploadRes.text()
      throw new Error(`YouTube upload failed: ${err.slice(0, 200)}`)
    }

    const result = await uploadRes.json()
    return result.id
  },
}
