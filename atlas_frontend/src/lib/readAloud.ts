/** One local audio player shared by answer footers, dictation, and voice previews. */
import { useSyncExternalStore } from 'react'

import { synthesizeVoice } from './api'

type Phase = 'idle' | 'loading' | 'playing' | 'blocked' | 'error'
type Playback = { id: string | null; phase: Phase; error: string }
let state: Playback = { id: null, phase: 'idle', error: '' }
const listeners = new Set<() => void>()
let generation = 0
let audio: HTMLAudioElement | null = null
let url: string | null = null
let request: AbortController | null = null

function update(next: Playback) {
  state = next
  listeners.forEach((notify) => notify())
}

function releaseAudio() {
  if (audio) {
    audio.onended = null
    audio.onerror = null
    audio.pause()
    audio.removeAttribute('src')
    audio.load()
    audio = null
  }
  if (url) URL.revokeObjectURL(url)
  url = null
}

export function stopReadAloud() {
  generation += 1
  request?.abort()
  request = null
  releaseAudio()
  update({ id: null, phase: 'idle', error: '' })
}

/** Retain the complete answer, including values, while removing visual Markdown syntax. */
export function speechChunks(markdown: string): string[] {
  const text = markdown
    .replace(/```[\s\S]*?```/g, ' Code block omitted. ')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^\s*#{1,6}\s+/gm, '')
    .replace(/^\s*[-*+]\s+/gm, '')
    .replace(/[`*|]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  // Small batches start speaking promptly; long responses are never truncated.
  return text.match(/.{1,700}(?:\s|$)|\S{1,700}/g)?.map((part) => part.trim()) ?? []
}

export async function resumeReadAloud() {
  if (!audio) return
  const token = generation
  try {
    await audio.play()
    if (token === generation) update({ ...state, phase: 'playing', error: '' })
  } catch (error) {
    if (token !== generation) return
    const blocked = error instanceof DOMException && error.name === 'NotAllowedError'
    update({ ...state, phase: blocked ? 'blocked' : 'error', error: blocked
      ? 'Your browser paused autoplay. Tap Play audio to listen.'
      : 'Audio could not play. Try Read aloud again.' })
  }
}

export function readAloud(id: string, content: string, voice?: string) {
  stopReadAloud()
  const token = generation
  const chunks = speechChunks(content)
  if (!chunks.length) return
  const next = async (index: number): Promise<void> => {
    if (token !== generation) return
    const chunk = chunks[index]
    if (!chunk) return
    releaseAudio()
    update({ id, phase: 'loading', error: '' })
    request = new AbortController()
    try {
      const blob = await synthesizeVoice(chunk, request.signal, voice)
      if (token !== generation) return
      url = URL.createObjectURL(blob)
      audio = new Audio(url)
      audio.onended = () => {
        if (token !== generation) return
        if (index + 1 < chunks.length) void next(index + 1)
        else stopReadAloud()
      }
      audio.onerror = () => {
        if (token === generation) update({ id, phase: 'error', error: 'Audio could not play. Try again.' })
      }
      await resumeReadAloud()
    } catch (error) {
      if (token !== generation) return
      update({ id, phase: 'error', error: error instanceof Error ? error.message : 'Local speech failed.' })
    }
  }
  void next(0)
}

function subscribe(notify: () => void) {
  listeners.add(notify)
  return () => { listeners.delete(notify) }
}

export function useReadAloud() {
  return useSyncExternalStore(subscribe, () => state)
}
