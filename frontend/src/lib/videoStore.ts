/**
 * IndexedDB video store — client-side video cache.
 *
 * Two stores:
 * - "attempts": recorded attempt blobs (primary playback source, Pi never serves these back)
 * - "routines": cached routine videos (downloaded once from Pi, used for HTML5 playbackRate speed control)
 */

const DB_NAME = 'dance-toolkit-videos'
const DB_VERSION = 2
const ATTEMPT_STORE = 'attempts'
const ROUTINE_STORE = 'routines'

function openDB(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION)
    req.onupgradeneeded = () => {
      const db = req.result
      if (!db.objectStoreNames.contains(ATTEMPT_STORE)) {
        db.createObjectStore(ATTEMPT_STORE)
      }
      if (!db.objectStoreNames.contains(ROUTINE_STORE)) {
        db.createObjectStore(ROUTINE_STORE)
      }
    }
    req.onsuccess = () => resolve(req.result)
    req.onerror = () => reject(req.error)
  })
}

// --- Attempt videos (recordings) ---

export async function saveVideo(attemptId: number, blob: Blob): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ATTEMPT_STORE, 'readwrite')
    tx.objectStore(ATTEMPT_STORE).put(blob, attemptId)
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => { db.close(); reject(tx.error) }
  })
}

export async function getVideo(attemptId: number): Promise<Blob | null> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ATTEMPT_STORE, 'readonly')
    const req = tx.objectStore(ATTEMPT_STORE).get(attemptId)
    req.onsuccess = () => { db.close(); resolve(req.result || null) }
    req.onerror = () => { db.close(); reject(req.error) }
  })
}

export async function deleteVideo(attemptId: number): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ATTEMPT_STORE, 'readwrite')
    tx.objectStore(ATTEMPT_STORE).delete(attemptId)
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => { db.close(); reject(tx.error) }
  })
}

// --- Routine videos (cached downloads for client-side speed control) ---

export async function saveRoutineVideo(routineId: number, blob: Blob): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ROUTINE_STORE, 'readwrite')
    tx.objectStore(ROUTINE_STORE).put(blob, routineId)
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => { db.close(); reject(tx.error) }
  })
}

export async function getRoutineVideo(routineId: number): Promise<Blob | null> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ROUTINE_STORE, 'readonly')
    const req = tx.objectStore(ROUTINE_STORE).get(routineId)
    req.onsuccess = () => { db.close(); resolve(req.result || null) }
    req.onerror = () => { db.close(); reject(req.error) }
  })
}

export async function deleteRoutineVideo(routineId: number): Promise<void> {
  const db = await openDB()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(ROUTINE_STORE, 'readwrite')
    tx.objectStore(ROUTINE_STORE).delete(routineId)
    tx.oncomplete = () => { db.close(); resolve() }
    tx.onerror = () => { db.close(); reject(tx.error) }
  })
}
