import { create } from 'zustand'
import { stages } from './data/caseData'
import type { Screen } from './data/types'

/**
 * Front-end stand-in for real stage execution: until the engine is wired up the
 * screen fakes each stage's duration from the time it reports, compressed so a
 * full run reads as a run rather than a wait. Delete once stages are driven by
 * the backend.
 */
const stageDelay = (i: number) =>
  Math.min(700, Math.max(120, parseFloat(stages[i].time) * 60))

interface AppState {
  screen: Screen
  /** Whether the processing pipeline has run to completion for this case. */
  pipelineComplete: boolean
  /** Number of pipeline stages finished so far; also the index of the next one. */
  stagesDone: number
  /** Index of the stage currently executing, or null when the pipeline is idle. */
  runningStage: number | null
  selectedTx: string
  selectedRecord: string
  reportFormat: string
  /** Ids of expanded correlation-graph groups. Collapsed by default. */
  expandedGroups: string[]

  go: (screen: Screen) => void
  /** Execute the next pending stage only, so the run can be stepped through. */
  runStage: () => void
  /** Execute every remaining stage back to back; `onDone` fires when the last finishes. */
  runAllStages: (onDone?: () => void) => void
  /** Return the pipeline to its unrun state. */
  resetPipeline: () => void
  selectTx: (id: string) => void
  selectRecord: (id: string) => void
  setFormat: (f: string) => void
  toggleGroup: (id: string) => void
  /** Jump to the Transactions view with a transaction selected. */
  openTransaction: (id: string) => void
  /** Jump to the Record History view with a record selected. */
  openRecord: (id: string) => void
}

type Set = (partial: Partial<AppState>) => void
type Get = () => AppState

/** Incremented by a reset so timeouts from an abandoned run land on nothing. */
let runToken = 0

/**
 * Run the next pending stage, then — when `all` is set — chain into the one
 * after it. Ignored while a stage is already in flight, so a double click on
 * either button cannot start two runs.
 */
const step = (set: Set, get: Get, all: boolean, onDone?: () => void) => {
  const { stagesDone, runningStage } = get()
  if (runningStage !== null) return
  if (stagesDone >= stages.length) {
    onDone?.()
    return
  }
  const token = runToken
  set({ runningStage: stagesDone })
  setTimeout(() => {
    if (token !== runToken) return
    const done = get().stagesDone + 1
    set({ stagesDone: done, runningStage: null, pipelineComplete: done >= stages.length })
    if (done >= stages.length) onDone?.()
    else if (all) step(set, get, true, onDone)
  }, stageDelay(stagesDone))
}

export const useApp = create<AppState>((set, get) => ({
  screen: 'recon',
  pipelineComplete: false,
  stagesDone: 0,
  runningStage: null,
  selectedTx: 'TX-1452',
  selectedRecord: 'accounts:101',
  reportFormat: 'PDF',
  expandedGroups: [],

  go: (screen) => set({ screen }),
  runStage: () => step(set, get, false),
  runAllStages: (onDone) => step(set, get, true, onDone),
  resetPipeline: () => {
    runToken += 1 // strand any stage still counting down
    set({ stagesDone: 0, runningStage: null, pipelineComplete: false })
  },
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
