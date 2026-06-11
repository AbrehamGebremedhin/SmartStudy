const BASE = '/api'

function getToken() {
  return localStorage.getItem('ss_token')
}

async function request(method, path, body) {
  const token = getToken()
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers['Authorization'] = `Bearer ${token}`

  let res
  try {
    res = await fetch(`${BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    })
  } catch {
    // Network unreachable, DNS failure, server down, CORS, etc.
    const e = new Error("Can't reach the server. Check your connection and try again.")
    e.isNetwork = true
    throw e
  }

  if (res.status === 401) {
    localStorage.removeItem('ss_token')
    window.dispatchEvent(new Event('ss:logout'))
    throw new Error('Unauthorized')
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail ?? err.message ?? 'Request failed')
  }

  if (res.status === 204) return null
  return res.json()
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  delete: (path) => request('DELETE', path),
}
