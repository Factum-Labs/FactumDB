import { create } from 'zustand'
import type { Screen, ShellMode } from './data/types'

interface AppState {
  screen: Screen
  shell: ShellMode
  selectedTx: string
  selectedRecord: string
  reportFormat: string
  /** Ids of expanded correlation-graph groups. Collapsed by default. */
  expandedGroups: string[]

  go: (screen: Screen) => void
  cycleShell: () => void
  selectTx: (id: string) => void
  selectRecord: (id: string) => void
  setFormat: (f: string) => void
  toggleGroup: (id: string) => void
  /** Jump to the Transactions view with a transaction selected. */
  openTransaction: (id: string) => void
  /** Jump to the Record History view with a record selected. */
  openRecord: (id: string) => void
}

const SHELL_CYCLE: Record<ShellMode, ShellMode> = {
  sidebar: 'rail',
  rail: 'topbar',
  topbar: 'sidebar',
}

export const useApp = create<AppState>((set) => ({
  screen: 'recon',
  shell: 'sidebar',
  selectedTx: 'TX-1452',
  selectedRecord: 'accounts:101',
  reportFormat: 'PDF',
  expandedGroups: [],

  go: (screen) => set({ screen }),
  cycleShell: () => set((s) => ({ shell: SHELL_CYCLE[s.shell] })),
  selectTx: (selectedTx) => set({ selectedTx }),
  selectRecord: (selectedRecord) => set({ selectedRecord }),
  setFormat: (reportFormat) => set({ reportFormat }),
  toggleGroup: (id) =>
    set((s) => ({
      expandedGroups: s.expandedGroups.includes(id)
        ? s.expandedGroups.filter((g) => g !== id)
        : [...s.expandedGroups, id],
    })),
  openTransaction: (id) => set({ screen: 'timeline', selectedTx: id }),
  openRecord: (id) => set({ screen: 'record', selectedRecord: id }),
}))
