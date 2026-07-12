import { apiRequest } from "./client"

export type OverviewResponse = {
  days: number
  from: string
  to: string
  total_tasks: number
  completed_tasks: number
  missed_tasks: number
  completion_rate: number
  streak: number
  habits_count: number
}

export type DailyPoint = {
  date: string
  total: number
  completed: number
  missed: number
}

export type DailySeriesResponse = {
  from: string
  to: string
  series: DailyPoint[]
}

export type ScheduleItem = {
  id: number
  title: string
  date: string
  start_time: string
  end_time: string | null
  is_completed: boolean
  is_placeholder: boolean
  habit_id: number | null
}

export type ScheduleResponse = {
  from: string
  to: string
  items: ScheduleItem[]
}

export function fetchOverview(days = 7): Promise<OverviewResponse> {
  return apiRequest<OverviewResponse>(`/api/v1/stats/overview?days=${days}`)
}

export function fetchDaily(
  from: string,
  to: string,
): Promise<DailySeriesResponse> {
  const q = new URLSearchParams({ from, to })
  return apiRequest<DailySeriesResponse>(`/api/v1/stats/daily?${q}`)
}

export function fetchSchedule(
  from: string,
  to: string,
): Promise<ScheduleResponse> {
  const q = new URLSearchParams({ from, to })
  return apiRequest<ScheduleResponse>(`/api/v1/stats/schedule?${q}`)
}
