import { api } from './apiClient'

export function getHistory(limit = 50, offset = 0) {
  return api.get(`/history/?limit=${limit}&offset=${offset}`)
}

export function getHistoryByType(type, limit = 50, offset = 0) {
  return api.get(`/history/${type}?limit=${limit}&offset=${offset}`)
}
