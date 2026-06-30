// Cross-device sync for the gamification profile. Pull+merge on login,
// debounced push on every XP/achievement event. All failures are swallowed —
// localStorage stays the source of truth if the network is down.

import { api } from '../services/apiClient'
import { getProfile, setProfile, mergeProfiles } from './gamification'

let pushTimer = null
let wired = false

/** PUT the local profile to the server, debounced so a burst of XP = one write. */
export function pushProfile(delay = 4000) {
  clearTimeout(pushTimer)
  pushTimer = setTimeout(() => {
    api.put('/progress', { profile: getProfile() }).catch(() => {})
  }, delay)
}

/** GET server profile, merge into local, persist, and push the merged result back. */
export async function syncOnLogin() {
  try {
    const { profile: server } = await api.get('/progress')
    const merged = mergeProfiles(getProfile(), server ?? {})
    setProfile(merged)
    window.dispatchEvent(new Event('ss:profilesynced'))
    await api.put('/progress', { profile: merged }).catch(() => {})
  } catch {
    // offline or unauthorized — keep local profile as-is
  }
}

/** Wire once at app start: push on every gamification mutation. */
export function startProgressSync() {
  if (wired) return  // idempotent: PrivateRoute may re-run on user-object changes
  wired = true
  const onChange = () => pushProfile()
  window.addEventListener('ss:xp', onChange)
  window.addEventListener('ss:levelup', onChange)
  window.addEventListener('ss:achievement', onChange)
}
