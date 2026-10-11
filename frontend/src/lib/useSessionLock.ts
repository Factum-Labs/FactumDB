import { useEffect } from 'react'
import { useApp } from '../store'
import { request, type AuthStatus } from './backend'

export function useSessionLock() {
  const username = useApp(s => s.user?.username)
  const locked = useApp(s => s.locked)
  const minutes = useApp(s => s.settings?.preferences?.lock_minutes ?? 15)
  useEffect(() => {
    if (!username || locked) return
    let activity = Date.now()
    let sent = 0
    let checking = false
    const touch = () => {
      if (minutes && Date.now() - activity >= minutes * 60000) {
        void useApp.getState().lockSession(); return
      }
      activity = Date.now()
      if (activity - sent < 10000) return
      sent = activity
      void request('auth_touch').catch(error => useApp.getState().setError(error))
    }
    const events = ['pointerdown', 'pointermove', 'keydown', 'wheel'] as const
    for (const event of events) window.addEventListener(event, touch, { passive: true })
    const timer = window.setInterval(() => {
      if (minutes && Date.now() - activity >= minutes * 60000) {
        void useApp.getState().lockSession(); return
      }
      if (checking || useApp.getState().busy) return
      checking = true
      void request<AuthStatus>('auth_status').then(status => {
        if (status.locked) useApp.setState({ locked: true })
        else if (!status.user) void useApp.getState().signOut()
      }).catch(error => useApp.getState().setError(error)).finally(() => { checking = false })
    }, 1000)
    return () => {
      window.clearInterval(timer)
      for (const event of events) window.removeEventListener(event, touch)
    }
  }, [username, locked, minutes])
}
